import {act, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {ApiError} from '../../api/client';
import {routeFetch} from '../../testing/admin';
import {JobFeedback} from './JobFeedback';
import {refusal} from './useJobLauncher';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('refusal', () => {
  it('turns a 409 into the running job with a link', async () => {
    routeFetch({});
    const state = refusal(
      new ApiError(409, 'job_running', 'the backup job 3f2a is running', null, {
        code: 'job_running',
        message: 'the backup job 3f2a is running',
        job_id: '3f2a9c0d1e4b5a67',
      }),
    );
    expect(state).toEqual({
      kind: 'busy',
      jobId: '3f2a9c0d1e4b5a67',
      message: 'the backup job 3f2a is running',
    });
    await act(async () => {
      render(<JobFeedback state={state} />);
    });
    expect(screen.getByTestId('job-busy-link')).toHaveAttribute(
      'href',
      '/jobs/3f2a9c0d1e4b5a67',
    );
  });

  it('names the nightly job when no job ID holds the slot', () => {
    const state = refusal(
      new ApiError(409, 'job_running', 'the nightly refresh runs', null, {
        job_id: null,
      }),
    );
    render(<JobFeedback state={state} />);
    expect(screen.getByTestId('job-busy')).toHaveTextContent('nightly job');
  });

  it('names the failed parameters and the confirmation', () => {
    expect(
      refusal(
        new ApiError(400, 'invalid_params', 'bad', null, {fields: ['ticker']}),
      ),
    ).toEqual({kind: 'failed', message: 'bad (ticker)'});
    expect(
      refusal(
        new ApiError(400, 'confirm_mismatch', 'no', null, {confirm: 'rebuild'}),
      ),
    ).toEqual({
      kind: 'failed',
      message: 'The confirmation did not match: the job needs "rebuild".',
    });
    expect(refusal(new ApiError(403, 'forbidden', 'no', null))).toEqual({
      kind: 'failed',
      message: 'Only an admin can run this job.',
    });
    expect(refusal(new Error('x'))).toEqual({
      kind: 'failed',
      message: 'The job could not be sent.',
    });
  });
});
