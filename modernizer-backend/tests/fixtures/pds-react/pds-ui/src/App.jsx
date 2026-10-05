import React from 'react';
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom';
import JobList from './pages/JobList';
import JobStatus from './pages/JobStatus';
import AttributeSearch from './pages/AttributeSearch';

export default function App() {
  return (
    <BrowserRouter>
      <nav><Link to="/job_list">PDS Dashboard</Link> <Link to="/job_status">Links...</Link></nav>
      <Routes>
        <Route path="/job_list" element={<JobList />} />
        <Route path="/job_status" element={<JobStatus />} />
        <Route path="/attribute_search" element={<AttributeSearch />} />
      </Routes>
    </BrowserRouter>
  );
}
