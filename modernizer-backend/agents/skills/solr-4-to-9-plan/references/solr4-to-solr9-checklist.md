# Solr 4.x → Solr 9.x Migration Checklist

Solr 4 to 9 spans five major versions (5, 6, 7, 8, 9) — treat this as
cumulative, not just the final Solr 9 surface.

## Schema Changes

| Item | Changed in | Action |
|---|---|---|
| `Trie*Field` types | Deprecated 7, removed 8 | Replace with Point field equivalents: `solr.IntPointField`, `solr.LongPointField`, `solr.FloatPointField`, `solr.DoublePointField`, `solr.DatePointField` |
| `_version_` field | Required since 4.0 | Ensure present, `indexed="true" stored="true"` |
| `docValues` | Increasingly required for sort/facet/group performance | Add `docValues="true"` to fields used for sorting, faceting, or grouping |
| `solr.LatLonType` | Deprecated | `solr.LatLonPointSpatialField` |
| String fields for exact-match | n/a | Prefer `solr.StrField` over deprecated tokenized-as-untokenized patterns |
| `<schema>` `version` attribute | n/a | Bump to `1.6` |

## solrconfig.xml Changes

| Item | Changed in | Action |
|---|---|---|
| `luceneMatchVersion` | Every major version | Bump to the target Solr version's bundled Lucene version (e.g. `9.6`) |
| `/update/extract` handler | Contrib packaging changed | Explicitly declare the extraction contrib `<lib>` entry, or remove the handler if unused |
| `solr.spelling.SpellingQueryConverter` | Removed 7 | Replace with `WordBreakSolrSpellChecker` or a current spellcheck component config |
| `<lib>` directory layout | Changed across versions | Update `<lib dir="...">` paths to the target version's contrib/lib layout |
| Default `maxWarmingSearchers`, cache sizing defaults | Tuned per version | Review against the target version's reference `solrconfig.xml` |
| `<solrcloud>` / ZooKeeper client config | State format changed 4→5 | If SolrCloud, verify no code/config assumes the old per-cluster `clusterstate.json` (replaced by per-collection `state.json`) |

## SolrJ Client API Changes

| Item | Changed in | Action |
|---|---|---|
| `HttpSolrServer` | Renamed | `HttpSolrClient` (built via `new HttpSolrClient.Builder(url).build()`) |
| `CloudSolrServer` | Renamed | `CloudSolrClient` (built via `new CloudSolrClient.Builder(zkHosts, ...).build()`) |
| `ConcurrentUpdateSolrServer` | Renamed | `ConcurrentUpdateSolrClient` |
| `solr-solrj` dependency version | n/a | Bump to the target Solr version's matching SolrJ release (client/server major versions should match) |
| Manual `HttpClient` wiring | API changed | Use `HttpSolrClient.Builder`'s `withHttpClient(...)` |

## Deployment / Reindexing (document in the plan's "Operational Follow-up" section — outside this pipeline's scope)
- A full reindex from the source system is the recommended path across a 4→9 jump; Lucene's on-disk index format is not forward-compatible across this many majors
- If reindexing from the existing index is unavoidable, document the version-by-version `IndexUpgraderTool` path (4→5→6→7→8→9) — this pipeline does not execute it
- ZooKeeper ensemble version compatibility for SolrCloud deployments

## Build Tooling
- Bump `solr-solrj` (and any `solr-core` test-scope dependency) version in `pom.xml`/`build.gradle` to the target Solr version
- Update any embedded Solr test dependency (`solr-test-framework`) to match
