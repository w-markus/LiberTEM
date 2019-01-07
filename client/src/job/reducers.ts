import { AllActions } from "../actions";
import * as channelActions from '../channel/actions';
import { ById, insertById, updateById } from "../helpers/reducerHelpers";
import * as jobActions from './actions';
import { JobRunning, JobState, JobStatus } from "./types";

export type JobReducerState = ById<JobState>;

const initialJobState: JobReducerState = {
    byId: {},
    ids: [],
};

export function jobReducer(state = initialJobState, action: AllActions): JobReducerState {
    switch (action.type) {
        case jobActions.ActionTypes.CREATE: {
            const createResult = insertById(
                state,
                action.payload.id,
                {
                    id: action.payload.id,
                    dataset: action.payload.dataset,
                    running: JobRunning.CREATING,
                    status: JobStatus.CREATING,
                    results: [],
                    startTimestamp: action.payload.timestamp,
                }
            )
            return createResult;
        }
        case channelActions.ActionTypes.JOB_STARTED: {
            return updateById(
                state,
                action.payload.job,
                {
                    running: JobRunning.RUNNING,
                    status: JobStatus.IN_PROGRESS,
                    startTimestamp: action.payload.timestamp,
                }
            )
        }
        case channelActions.ActionTypes.TASK_RESULT: {
            return updateById(
                state,
                action.payload.job,
                {
                    results: action.payload.results,
                }
            );
        }
        case channelActions.ActionTypes.FINISH_JOB: {
            const { job, timestamp, results } = action.payload;
            return updateById(
                state,
                job,
                {
                    running: JobRunning.DONE,
                    status: JobStatus.SUCCESS,
                    results,
                    endTimestamp: timestamp,
                }
            );
        }
        case channelActions.ActionTypes.JOB_ERROR: {
            const { job, timestamp } = action.payload;
            return updateById(
                state,
                job,
                {
                    running: JobRunning.DONE,
                    status: JobStatus.ERROR,
                    endTimestamp: timestamp,
                }
            )
        }
    }
    return state;
}