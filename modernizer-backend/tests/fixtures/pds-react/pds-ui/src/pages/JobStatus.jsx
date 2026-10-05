import React, { useEffect, useState } from 'react';
import { cancelExecution, fetchCompletedJobs, fetchRunningJobs } from '../api/jobs';

const REFRESH_MS = 10000;

export default function JobStatus() {
  const [running, setRunning] = useState([]);
  const [completed, setCompleted] = useState([]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [date, setDate] = useState(new Date());

  const loadRunning = () => fetchRunningJobs().then((res) => setRunning(res.data));

  useEffect(() => {
    loadRunning();
    if (!autoRefresh) return undefined;
    const timer = setInterval(loadRunning, REFRESH_MS);
    return () => clearInterval(timer);
  }, [autoRefresh]);

  useEffect(() => {
    fetchCompletedJobs(date.toISOString().slice(0, 10)).then((res) => setCompleted(res.data));
  }, [date]);

  const handleCancel = (execId) => {
    cancelExecution(execId).then(loadRunning);
  };

  const shift = (days) => setDate(new Date(date.getTime() + days * 86400000));

  return (
    <div>
      <h2>PDS Job Status</h2>
      <label>Auto-Refresh <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} /></label>
      <h3>Currently Running</h3>
      <table id="runningGrid">
        <thead><tr><th>Job ID</th><th>Job Name</th><th>Job Exec ID</th><th>Async Job ID</th><th>Status</th><th>Elapsed Time</th><th>Cancel</th></tr></thead>
        <tbody>
          {running.map((r) => (
            <tr key={r.jobExecId}>
              <td>{r.jobId}</td><td>{r.jobName}</td><td>{r.jobExecId}</td><td>{r.asyncJobId}</td><td>{r.status}</td><td>{r.elapsedTime}</td>
              <td><button onClick={() => handleCancel(r.jobExecId)}>Cancel</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Completed Jobs</h3>
      <button onClick={() => shift(-1)}>Previous day</button>
      <button onClick={() => setDate(new Date())}>Today</button>
      <button onClick={() => shift(1)}>Next day</button>
      <table id="completedGrid">
        <thead><tr><th>Job ID</th><th>Job Name</th><th>Job Exec ID</th><th>Async Job ID</th><th>Status</th><th>Started</th><th>Elapsed Time</th></tr></thead>
        <tbody>
          {completed.map((c) => (
            <tr key={c.jobExecId}><td>{c.jobId}</td><td>{c.jobName}</td><td>{c.jobExecId}</td><td>{c.asyncJobId}</td><td>{c.status}</td><td>{c.started}</td><td>{c.elapsedTime}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
