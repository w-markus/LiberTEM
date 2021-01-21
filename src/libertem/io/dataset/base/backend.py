import mmap
import logging

import numpy as np

from .file import File

log = logging.getLogger(__name__)


_r_n_d_cache = {}


class IOBackend:
    registry = {}

    def __init_subclass__(cls, id_=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if id_ is not None:
            cls.registry[id_] = cls

    def __init__(self):
        pass

    @classmethod
    def from_json(cls, msg):
        """
        Construct an instance from the already-decoded `msg`.
        """
        raise NotImplementedError()


class IOBackendImpl:
    def __init__(self):
        pass

    def need_copy(
        self, decoder, roi, native_dtype, read_dtype, tiling_scheme=None, fileset=None,
        sync_offset=0, corrections=None,
    ):
        # checking conditions in which "straight mmap" is not possible
        # straight mmap means our dataset can just return views into the underlying mmap object
        # as tiles and use them as they are in the UDFs

        # 1) if a roi is given, straight mmap doesn't work because there are gaps in the navigation
        # axis:
        if roi is not None:
            log.debug("have roi, need copy")
            return True

        # 2) if we need to decode data, or do dtype conversion, we can't return
        # views into the underlying file:
        if self._need_decode(decoder, native_dtype, read_dtype):
            log.debug("have decode, need copy")
            return True

        # 3) if we have less number of frames per file than tile depth, we need to copy
        if tiling_scheme and fileset:
            fileset_arr = fileset.get_as_arr()
            if np.min(fileset_arr[:, 1] - fileset_arr[:, 0]) < tiling_scheme.depth:
                log.debug("too large for fileset, need copy")
                return True

        # 4) if we apply corrections, we need to copy
        if corrections is not None and corrections.have_corrections():
            log.debug("have corrections, need copy")
            return True

        # 5) if a negative offset is given, we need to copy
        if sync_offset < 0:
            log.debug("negative offset is set, need copy")
            return True

        return False

    def get_max_io_size(self):
        return 2**20  # default: 1MiB blocks

    def _need_decode(self, decoder, native_dtype, read_dtype):
        # FIXME: even with dtype "mismatch", we can possibly do dtype
        # conversion, if the tile size is small enough! maybe benchmark this
        # vs. _get_tiles_w_copy?
        if native_dtype != read_dtype:
            return True
        if decoder is not None:
            return True
        return False

    def preprocess(self, data, tile_slice, corrections):
        if corrections is None:
            return
        corrections.apply(data, tile_slice)

    def get_tiles(
        self, tiling_scheme, fileset, read_ranges, roi, native_dtype, read_dtype, decoder,
        corrections,
    ):
        """
        Read tiles from `fileset`, as specified by the parameters.

        Usually, this is used to read the data for a single partition.

        Parameters
        ----------

        tiling_scheme : TilingScheme
            Specifies how the tiles should be shaped

        fileset : FileSet
            The files that should be read from. Note that the order in the `FileSet` is important,
            it must match the indices on the `read_ranges`.

        read_ranges : np.ndarray
            Read ranges, as generated by :meth:`FileSet.get_read_ranges`

        roi : np.ndarray
            Boolean array specifying which data should be read

        native_dtype : np.dtype
            The native on-disk data type. If there is no direct match to
            a numpy dtype, specify the closest dtype.

        read_dtype : np.dtype
            The data dtype into which the data is converted when reading

        corrections
            A set of corrections to apply in a preprocesing step
        """
        raise NotImplementedError()


class LocalFile(File):
    def open(self):
        # NOTE: for `readinto` to work, we must not switch off buffering here!
        # otherwise, `readinto` may return partial results, which can be hard to handle
        f = open(self._path, "rb")
        self._file = f
        self._raw_mmap = mmap.mmap(
            fileno=f.fileno(),
            length=0,
            # can't use offset for cutting off file header, as it needs to be
            # aligned to page size...
            offset=0,
            access=mmap.ACCESS_READ,
        )
        # self._raw_mmap.madvise(mmap.MADV_HUGEPAGE) # TODO - benchmark this!
        itemsize = np.dtype(self._native_dtype).itemsize
        assert self._frame_header % itemsize == 0
        assert self._frame_footer % itemsize == 0
        start = self._frame_header // itemsize
        stop = start + int(np.prod(self._sig_shape))
        if self._file_header != 0:
            # FIXME: keep the mmap object around maybe?
            self._raw_mmap = memoryview(self._raw_mmap)[self._file_header:]
        self._mmap = self._mmap_to_array(self._raw_mmap, start, stop)

    def _mmap_to_array(self, raw_mmap, start, stop):
        """
        Create an array from the raw memory map, stipping away
        frame headers and footers

        Parameters
        ----------

        raw_mmap : np.memmap or memoryview
            The raw memory map, with the file header already stripped away

        start : int
            Number of items cut away at the start of each frame (frame_header // itemsize)

        stop : int
            Number of items per frame (something like start + np.prod(sig_shape))
        """
        return np.frombuffer(raw_mmap, dtype=self._native_dtype).reshape(
            (self.num_frames, -1)
        )[:, start:stop]

    def close(self):
        self._mmap = None
        self._raw_mmap = None
        self._file.close()
        self._file = None

    def mmap(self):
        """
        Memory map for this file, with file header, frame header and frame footer cut off

        Used for reading tiles straight from the filesystem cache
        """
        return self._mmap

    def raw_mmap(self):
        """
        Memory map for this file, with only the file header cut off

        Used for reading tiles with a decoding step, using the read ranges
        """
        return self._raw_mmap

    def readinto(self, out):
        """
        Fill `out` by reading from the current file position
        """
        return self._file.readinto(out)

    def seek(self, pos):
        self._file.seek(pos)

    def tell(self):
        return self._file.tell()

    def fileno(self):
        return self._file.fileno()
