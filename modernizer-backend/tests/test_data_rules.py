"""
Rules expressed as data rather than branches — lookup tables and patterns,
template/configuration files, and business filters inside SQL — found by
parsing, deterministically.
"""
from pathlib import Path

from agents.shared import rule_candidates as rc


def _write(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def _by_kind(root, kind):
    return [c for c in rc.scan(str(root)).candidates if c.kind == kind]


def test_java_lookup_tables_and_patterns_are_candidates(tmp_path):
    _write(tmp_path, {"src/main/java/a/Norm.java": """package a;
import java.util.*;
import java.util.regex.Pattern;
public class Norm {
    private static final Logger LOG = LoggerFactory.getLogger(Norm.class);
    private static final Map<String, String> COLOR_MAP = Map.of("NAVY", "Blue", "CRIMSON", "Red");
    private static final Set<String> EXCLUDED_COUNTRIES = Set.of("CU", "IR", "KP");
    private static final String[] SIZES = {"XS", "S", "M", "L"};
    private static final Pattern UPC = Pattern.compile("^\\\\d{12}$");
    private static final Map<String, Integer> ORDER = new HashMap<>();
    static { ORDER.put("SMALL", 1); ORDER.put("LARGE", 2); }
    private final ItemService service = new ItemService();
    private static final List<String> EMPTY = new ArrayList<>();
    public String normalize(String c) { Map<String, String> local = Map.of("a", "b"); return COLOR_MAP.getOrDefault(c, c); }
}
"""})
    [lookup] = _by_kind(tmp_path, "lookup")
    assert lookup.signals == ["COLOR_MAP, EXCLUDED_COUNTRIES, SIZES, UPC, static { … }"]
    assert 'Set.of("CU", "IR", "KP")' in lookup.source and 'ORDER.put("SMALL", 1)' in lookup.source
    assert "LOG" not in lookup.source and "service" not in lookup.source and "EMPTY" not in lookup.source
    assert "local" not in lookup.source                                     # method locals are not tables


def test_python_lookup_tables_and_patterns_are_candidates(tmp_path):
    _write(tmp_path, {"jobs/norm.py": """import re
COLOR_MAP = {"NAVY": "Blue", "CRIMSON": "Red", "IVORY": "White"}
EXCLUDED = ("CU", "IR", "KP")
UPC = re.compile(r"^\\d{12}$")
SMALL = {"a": 1}
NAMES = [first(), second(), third()]
"""})
    [lookup] = _by_kind(tmp_path, "lookup")
    assert lookup.language == "Python" and lookup.signals == ["COLOR_MAP, EXCLUDED, UPC"]


def test_template_and_reference_data_files_are_candidates_and_build_files_are_not(tmp_path):
    long_yaml = "ranges:\n" + "".join(f"  - {{label: r{i}, max: {i}}}\n" for i in range(30))  # 31 lines
    _write(tmp_path, {
        "pds-javaflux/src/main/resources/templates/mattress-height.json": '{"min": 4, "max": 22, "unit": "in"}',
        "pds-javaflux/src/main/resources/templates/diamond-weight.yml": long_yaml,
        "pds-javaflux/src/main/resources/rules/country-exclusion.xml": "<exclude><country>CU</country></exclude>",
        "pds-javaflux/src/main/resources/data/colors.csv": "raw,standard\nNAVY,Blue\n",
        "pds-service/src/main/resources/templates/dashboard/index.html": "<html></html>",     # a view, not data
        "pds-service/src/main/resources/application-bcom-prod.properties": "pds.batch.size=5000",
        "pds-service/src/main/resources/log4j2.xml": "<Configuration/>",
        "pom.xml": "<project/>", "web/package.json": "{}",
        "pds-service/src/main/resources/rules/.github/x.yml": "a: 1",
        "src/test/resources/templates/fixture.json": "{}",
    })
    found = {(c.path.rsplit("/", 1)[-1], c.symbol, c.language)
             for c in rc.scan(str(tmp_path), max_lines=25).candidates if c.kind == "config-rule"}
    assert found == {
        ("mattress-height.json", "mattress-height.json", "JSON"),
        ("diamond-weight.yml", "diamond-weight.yml (part 1/2)", "YAML"),
        ("diamond-weight.yml", "diamond-weight.yml (part 2/2)", "YAML"),
        ("country-exclusion.xml", "country-exclusion.xml", "XML"),
        ("colors.csv", "colors.csv", "CSV"),
    }
    parts = sorted((c.start, c.end) for c in rc.scan(str(tmp_path), max_lines=25).candidates
                   if c.kind == "config-rule" and "diamond" in c.path)
    assert parts == [(1, 25), (26, 31)]                                   # every line, in consecutive parts


def test_part_size_follows_the_candidate_line_limit(tmp_path):
    _write(tmp_path, {"rules/r.json": "\n".join(f'"k{i}": {i},' for i in range(12))})
    parts = [c for c in rc.scan(str(tmp_path), max_lines=5).candidates if c.kind == "config-rule"]
    assert [(c.start, c.end) for c in parts] == [(1, 5), (6, 10), (11, 12)]


def test_business_filters_inside_sql_are_candidates(tmp_path):
    _write(tmp_path, {
        "pds-dao/src/main/java/a/ItemDao.java": """package a;
public class ItemDao {
    private static final String ACTIVE_SQL = "SELECT * FROM ITEM WHERE STATUS_CD = 'A' AND DIV_NBR IN (71, 72)";
    private static final String TABLE = "ITEM";
    public java.util.List<Item> active() { return jdbc.query(ACTIVE_SQL, mapper); }
    public java.util.List<Item> byDept(int d) {
        return jdbc.query("SELECT upc FROM ITEM " + "WHERE DEPT_NBR = ? AND STATUS_CD <> 'D'", mapper, d);
    }
    public int count() { return jdbc.queryForObject("SELECT COUNT(*) FROM ITEM", Integer.class); }
    public void export(BigQuery bq) {
        if (bq == null) return;
        bq.query("SELECT upc FROM pds.items WHERE country NOT IN ('CU','IR')");
    }
}
""",
        "db/views.sql": """CREATE OR REPLACE VIEW ACTIVE_ITEMS AS
  SELECT * FROM ITEM WHERE STATUS_CD = 'A';
SELECT COUNT(*) FROM ITEM;
UPDATE ITEM SET STATUS_CD = 'D'
 WHERE LAST_SOLD < SYSDATE - 365;
""",
        "pds-dao/src/main/resources/mappers/ItemMapper.xml": """<?xml version="1.0"?>
<!DOCTYPE mapper PUBLIC "-//mybatis.org//DTD Mapper 3.0//EN" "http://mybatis.org/dtd/mybatis-3-mapper.dtd">
<mapper namespace="a.ItemMapper">
  <select id="findAll" resultType="Item">SELECT * FROM ITEM</select>
  <select id="findForBrand" resultType="Item">
    SELECT * FROM ITEM
    <where><if test="brand == 'BCOM'">AND BCOM_FLG = 'Y'</if></where>
  </select>
</mapper>
""",
    })
    queries = {c.symbol.rsplit(".", 1)[-1]: c for c in _by_kind(tmp_path, "query")}
    assert set(queries) == {"ItemDao", "byDept", "ACTIVE_ITEMS", "UPDATE at line 4", "findForBrand"}, queries
    assert queries["ItemDao"].signals == ["SQL constants: ACTIVE_SQL"] and "TABLE" not in queries["ItemDao"].source
    assert queries["byDept"].signals == ["sql-filter ×1"]
    export = next(c for c in rc.scan(str(tmp_path)).candidates if c.symbol.endswith(".export"))
    assert export.kind == "method" and export.status == "pending" and "sql-filter ×1" in export.signals
    assert "WHERE STATUS_CD = 'A'" in queries["ACTIVE_ITEMS"].source          # the view's SELECT on the next line
    assert queries["findForBrand"].language == "MyBatis XML" and "dynamic condition ×1" in queries["findForBrand"].signals
    kinds = {c.symbol.rsplit(".", 1)[-1]: c.kind for c in rc.scan(str(tmp_path)).candidates}
    assert "count" not in kinds and "active" not in kinds and "findAll" not in kinds  # no filter, no rule
