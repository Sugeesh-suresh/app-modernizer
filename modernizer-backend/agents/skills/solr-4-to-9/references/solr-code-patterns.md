# Solr 4.x → 9.x Code & Config Patterns

## Schema: Trie field → Point field
```xml
<!-- Before -->
<fieldType name="tint" class="solr.TrieIntField" precisionStep="8" positionIncrementGap="0"/>

<!-- After -->
<fieldType name="tint" class="solr.IntPointField" docValues="true" positionIncrementGap="0"/>
```

## solrconfig.xml: luceneMatchVersion bump
```xml
<!-- Before -->
<luceneMatchVersion>4.10</luceneMatchVersion>

<!-- After -->
<luceneMatchVersion>9.6</luceneMatchVersion>
```

## SolrJ: HttpSolrServer → HttpSolrClient
```java
// Before (SolrJ 4.x)
SolrServer server = new HttpSolrServer("http://localhost:8983/solr/mycore");
server.add(doc);
server.commit();

// After (SolrJ 9.x)
SolrClient client = new HttpSolrClient.Builder("http://localhost:8983/solr/mycore").build();
client.add(doc);
client.commit();
```

## SolrJ: CloudSolrServer → CloudSolrClient
```java
// Before
CloudSolrServer server = new CloudSolrServer("zk1:2181,zk2:2181/solr");
server.setDefaultCollection("mycollection");

// After
CloudSolrClient client = new CloudSolrClient.Builder(List.of("zk1:2181", "zk2:2181"), Optional.of("/solr"))
    .build();
client.setDefaultCollection("mycollection");
```
