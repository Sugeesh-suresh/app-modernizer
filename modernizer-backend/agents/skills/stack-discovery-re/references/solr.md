# Apache Solr — what to document

Where to look:
- Core/collection configuration: `solrconfig.xml`, `schema.xml`/`managed-schema`, `solr.xml`, `core.properties`, stopwords/synonyms/protwords files, `elevate.xml`, DIH configuration (`data-config.xml`)
- Client code: SolrJ (`org.apache.solr.client.*`), HTTP calls to `/select`, `/update` and other handlers, Spring Data Solr
- Indexing jobs, scripts and scheduled tasks that feed the index

What to record:
- Every core/collection, its fields (name, type, indexed, stored, multiValued, docValues), copyFields, dynamic fields, unique key and field types with their analysers
- Request handlers, search components, update processors and their parameters
- Caches, commit and autoCommit settings, replication/cloud configuration as present
- How the application indexes data: source of documents, mapping from entities to fields, triggers and frequency
- How the application queries: query parsers, filters, facets, sorting, highlighting, paging, and the screens or APIs that use them
- Solr URLs and client configuration (credentials redacted)
- Tests that exercise indexing or search and what they need to run
