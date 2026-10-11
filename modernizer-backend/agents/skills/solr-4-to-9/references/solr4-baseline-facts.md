# Solr 4.x Baseline — Patterns to Look For

## Schema tells (schema.xml)
- `<fieldType class="solr.TrieIntField">` / `TrieLongField` / `TrieFloatField` / `TrieDoubleField` / `TrieDateField` — Trie* numeric/date fields (removed in Solr 8, replaced by Point fields)
- `<field name="_version_" ... indexed="false">` or missing `_version_` entirely — required, indexed, for optimistic concurrency and real-time get
- `<fieldType class="solr.LatLonType">` — deprecated, replaced by `solr.LatLonPointSpatialField`
- No `docValues="true"` on fields used for sorting/faceting — became effectively required for performance at scale in modern Solr
- `<schema version="1.5">` or lower `version` attribute on the root `<schema>` element

## solrconfig.xml tells
- `<requestHandler name="/update/extract" class="solr.extraction.ExtractingRequestHandler">` registered implicitly by an old example config — the extraction (Solr Cell) contrib must be explicitly added as a dependency in modern Solr
- `class="solr.spelling.SpellingQueryConverter"` — removed in Solr 7
- `<luceneMatchVersion>4.x</luceneMatchVersion>` (or absent) — must be bumped to match the target Solr's bundled Lucene version
- Old-style `<lib dir="../../../contrib/..." regex=".*\.jar" />` paths referencing a Solr 4 directory layout (contrib/lib layout changed across versions)
- `<solrcloud>` section absent (deployment is standalone) vs a `<zkHost>` (SolrCloud) — a Solr 4 SolrCloud deployment's ZooKeeper `clusterstate.json` format changed to per-collection `state.json` in Solr 5+; flag if config assumes the old format

## SolrJ client tells
- `org.apache.solr.client.solrj.impl.HttpSolrServer` — renamed to `HttpSolrClient` in SolrJ 5
- `org.apache.solr.client.solrj.impl.CloudSolrServer` — renamed to `CloudSolrClient` (and its builder API changed) in SolrJ 5
- `new SolrQuery().setQueryType(...)` combined with old `SolrServer` subclasses
- Manual `HttpClient` configuration passed to `HttpSolrServer` — the modern `HttpSolrClient.Builder` API replaces this
- `solr-solrj` dependency version `4.x` in `pom.xml`/`build.gradle`

## Deployment / operational tells (call out in the BRD as an operational risk, not something the code migration itself performs)
- Index directories on disk — Lucene's on-disk index format from Solr 4's bundled Lucene version is NOT directly readable by Solr 9; a full reindex (or the `IndexUpgrader` tool run version-by-version) is required, independent of any config/code change
- ZooKeeper ensemble config referenced by an old `zkHost` connection string format
