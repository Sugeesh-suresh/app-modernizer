import React, { useEffect, useState } from 'react';
import { fetchAttribute, fetchAttributes, searchAttributes } from '../api/attributes';

const PAGE_SIZE = 20;

export default function AttributeSearch() {
  const [page, setPage] = useState(0);
  const [showValues, setShowValues] = useState(false);
  const [idFilter, setIdFilter] = useState('');
  const [nameFilter, setNameFilter] = useState('');
  const [result, setResult] = useState({ content: [], totalPages: 0, number: 0 });
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    fetchAttributes(page, PAGE_SIZE, showValues).then((res) => setResult(res.data));
  }, [page, showValues]);

  const onSearch = () => {
    searchAttributes(idFilter || undefined, nameFilter || undefined, 0).then((res) => setResult(res.data));
  };

  const openAttribute = (id) => fetchAttribute(id).then((res) => setDetail(res.data));

  return (
    <div>
      <h2>Attribute Search</h2>
      <input id="attrId" placeholder="ID" value={idFilter} onChange={(e) => setIdFilter(e.target.value)} />
      <input id="attrName" placeholder="Name" value={nameFilter} onChange={(e) => setNameFilter(e.target.value)} />
      <button id="attrSearch" onClick={onSearch}>Search</button>
      <label><input type="checkbox" checked={showValues} onChange={(e) => setShowValues(e.target.checked)} />Show Values</label>
      <div className="pager">
        <button onClick={() => setPage(0)}>First</button>
        <button onClick={() => setPage(page - 1)}>Previous</button>
        <span>page {result.number + 1} of {result.totalPages}</span>
        <button onClick={() => setPage(page + 1)}>Next</button>
        <button onClick={() => setPage(result.totalPages - 1)}>Last</button>
      </div>
      <table id="attributeGrid">
        <thead><tr><th>ID</th><th>ContextId</th><th>RefTag</th><th>Name</th><th>Avail</th><th>Tenant</th><th>Repeat</th><th>Display Value</th><th>Varchar Value</th><th>Seq</th><th>Type</th><th>EAP ID</th></tr></thead>
        <tbody>
          {result.content.map((a) => (
            <tr key={a.id}>
              <td><a href="#" onClick={() => openAttribute(a.id)}>{a.id}</a></td><td>{a.contextId}</td><td>{a.refTag}</td><td>{a.name}</td>
              <td>{a.avail}</td><td>{a.tenant}</td><td>{String(a.repeat)}</td><td>{a.displayValue}</td><td>{a.varcharValue}</td>
              <td>{a.seq}</td><td>{a.type}</td><td>{a.eapId}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
