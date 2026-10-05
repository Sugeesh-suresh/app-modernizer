import React, { useEffect, useState } from 'react';
import { fetchJobs, searchJobs } from '../api/jobs';

export default function JobList() {
  const [tenant] = useState('MCOM');
  const [env] = useState('DEV');
  const [view, setView] = useState('Standard');
  const [search, setSearch] = useState('');
  const [scope, setScope] = useState('VISIBLE');
  const [exact, setExact] = useState(false);
  const [data, setData] = useState({ jobs: [], total: 0 });

  const loadJobs = () => {
    fetchJobs({ tenant, env, view }).then((res) => setData(res.data));
  };

  useEffect(() => {
    loadJobs();
  }, [view]);

  const runSearch = () => {
    searchJobs(search, scope, exact, tenant).then((res) => setData(res.data));
  };

  return (
    <div>
      <h2>PDS Self Service Job List</h2>
      <p>Displaying {data.tenant} data from {data.environment}</p>
      <input id="jobSearch" value={search} onChange={(e) => setSearch(e.target.value)}
             onKeyDown={(e) => e.key === 'Enter' && runSearch()} />
      <select id="searchScope" value={scope} onChange={(e) => setScope(e.target.value)}>
        <option value="VISIBLE">Search Visible</option>
        <option value="ALL">Search All</option>
      </select>
      <label><input type="checkbox" checked={exact} onChange={(e) => setExact(e.target.checked)} />Exact Search</label>
      <select id="viewSelect" value={view} onChange={(e) => setView(e.target.value)}>
        <option>Standard</option>
        <option>Detailed</option>
      </select>
      <span>{data.total} jobs</span>
      <table id="jobGrid">
        <thead><tr><th>Job ID</th><th>Job Name</th><th>Status</th><th>Attribute</th><th>Attribute Type</th><th>Edit</th><th>Run</th><th>Non-Approved Only</th></tr></thead>
        <tbody>
          {data.jobs.map((job) => (
            <tr key={job.jobId}>
              <td>{job.jobId}</td><td>{job.jobName} {job.warnings.join(' ')}</td><td>{job.status}</td>
              <td>{job.attributeId}</td><td>{job.attributeType}</td><td>{job.editable ? 'Y' : 'N'}</td>
              <td>{job.runnable ? 'Y' : 'N'}</td><td>{job.nonApprovedOnly ? 'Y' : 'N'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
