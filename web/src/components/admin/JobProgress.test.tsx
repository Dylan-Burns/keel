import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import type {Job} from '../../api/types';
import {job} from '../../testing/admin';
import {JobProgress} from './JobProgress';
import {JobsTable} from './JobsTable';

/** A job record as the API sends it before the first progress report. */
function withoutProgress(): Job {
  const entries = Object.entries(job({status: 'queued'}));
  return Object.fromEntries(
    entries.filter(([key]) => key !== 'progress'),
  ) as unknown as Job;
}

describe('JobProgress', () => {
  it('renders a job record that has no progress yet', () => {
    render(<JobProgress job={withoutProgress()} />);
    expect(screen.getByTestId('job-progress')).toBeInTheDocument();
  });
});

describe('JobsTable', () => {
  it('renders an empty progress cell for a job with no progress', () => {
    render(<JobsTable jobs={[withoutProgress()]} selected={null} />);
    expect(screen.getByRole('table')).toBeInTheDocument();
  });
});
