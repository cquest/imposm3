import math
import tempfile
import shutil
import subprocess
import psycopg2
import psycopg2.extras
import json
from  shapely.wkb import loads as wkb_loads
from shapely.geometry import Point
import binascii

import unittest

class Dummy(unittest.TestCase):
    def nop():
        pass
_t = Dummy('nop')
assert_almost_equal = _t.assertAlmostEqual

tmpdir = None

def setup():
    global tmpdir
    tmpdir = tempfile.mkdtemp()

def teardown():
    shutil.rmtree(tmpdir)
    drop_test_schemas()


db_conf = {
    'host': 'localhost',
}

TEST_SCHEMA_IMPORT = "imposm3testimport"
TEST_SCHEMA_PRODUCTION = "imposm3testpublic"
TEST_SCHEMA_BACKUP = "imposm3testbackup"

def merc_point(lon, lat):
    pole = 6378137 * math.pi # 20037508.342789244

    x = lon * pole / 180.0
    y = math.log(math.tan((90.0+lat)*math.pi/360.0)) / math.pi * pole
    return Point(x, y)


def pg_db_url(db_conf):
    return 'postgis://%(host)s' % db_conf

def create_geom_in_row(rowdict):
    if rowdict:
        rowdict['geometry'] = wkb_loads(binascii.unhexlify(rowdict['geometry']))
    return rowdict

def query_row(db_conf, table, osmid):
    conn = psycopg2.connect(**db_conf)
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute('select * from %s.%s where osm_id = %%s' % (TEST_SCHEMA_PRODUCTION, table), [osmid])
    results = []
    for row in cur.fetchall():
        create_geom_in_row(row)
        results.append(row)

    if not results:
        return None
    if len(results) == 1:
        return results[0]
    return results

def imposm3_import(db_conf, pbf):
    conn = pg_db_url(db_conf)

    try:
        print subprocess.check_output((
            "../imposm3 import -connection %s -read %s"
            " -write"
            " -cachedir %s"
            " -diff"
            " -overwritecache"
            " -dbschema-import " + TEST_SCHEMA_IMPORT +
            " -optimize"
            " -mapping test_mapping.json ") % (
            conn, pbf, tmpdir,
        ), shell=True)
    except subprocess.CalledProcessError, ex:
        print ex.output
        raise

def imposm3_deploy(db_conf):
    conn = pg_db_url(db_conf)

    try:
        print subprocess.check_output((
            "../imposm3 import -connection %s"
            " -dbschema-import " + TEST_SCHEMA_IMPORT +
            " -dbschema-production " + TEST_SCHEMA_PRODUCTION +
            " -dbschema-backup " + TEST_SCHEMA_BACKUP +
            " -deployproduction"
            " -mapping test_mapping.json ") % (
            conn,
        ), shell=True)
    except subprocess.CalledProcessError, ex:
        print ex.output
        raise

def imposm3_revert_deploy(db_conf):
    conn = pg_db_url(db_conf)

    try:
        print subprocess.check_output((
            "../imposm3 import -connection %s"
            " -dbschema-import " + TEST_SCHEMA_IMPORT +
            " -dbschema-production " + TEST_SCHEMA_PRODUCTION +
            " -dbschema-backup " + TEST_SCHEMA_BACKUP +
            " -revertdeploy"
            " -mapping test_mapping.json ") % (
            conn,
        ), shell=True)
    except subprocess.CalledProcessError, ex:
        print ex.output
        raise

def imposm3_remove_backups(db_conf):
    conn = pg_db_url(db_conf)

    try:
        print subprocess.check_output((
            "../imposm3 import -connection %s"
            " -dbschema-backup " + TEST_SCHEMA_BACKUP +
            " -removebackup"
            " -mapping test_mapping.json ") % (
            conn,
        ), shell=True)
    except subprocess.CalledProcessError, ex:
        print ex.output
        raise

def imposm3_update(db_conf, osc):
    conn = pg_db_url(db_conf)

    try:
        print subprocess.check_output((
            "../imposm3 diff -connection %s"
            " -cachedir %s"
            " -limitto clipping-3857.geojson"
            " -dbschema-production " + TEST_SCHEMA_PRODUCTION +
            " -mapping test_mapping.json %s") % (
            conn, tmpdir, osc,
        ), shell=True)
    except subprocess.CalledProcessError, ex:
        print ex.output
        raise

def cache_query(nodes='', ways='', relations='', deps='', full=''):
    if nodes:
        nodes = '-node ' + ','.join(map(str, nodes))
    if ways:
        ways = '-way ' + ','.join(map(str, ways))
    if relations:
        relations = '-rel ' + ','.join(map(str, relations))
    if deps:
        deps = '-deps'
    if full:
        full = '-full'
    out = subprocess.check_output(
        "../imposm3 query-cache -cachedir %s %s %s %s %s %s" % (
            tmpdir, nodes, ways, relations, deps, full),
        shell=True)
    print out
    return json.loads(out)

def table_exists(table, schema=TEST_SCHEMA_IMPORT):
    conn = psycopg2.connect(**db_conf)
    cur = conn.cursor()
    cur.execute("SELECT EXISTS(SELECT * FROM information_schema.tables WHERE table_name='%s' AND table_schema='%s')"
        % (table, schema))
    return cur.fetchone()[0]

def assert_missing_node(id):
    data = cache_query(nodes=[id])
    if data['nodes'][str(id)]:
        raise AssertionError('node %d found' % id)

def assert_cached_node(id, (lon, lat)=(None, None)):
    data = cache_query(nodes=[id])
    node = data['nodes'][str(id)]
    if not node:
        raise AssertionError('node %d not found' % id)

    if lon and lat:
        assert_almost_equal(lon, node['lon'], 6)
        assert_almost_equal(lat, node['lat'], 6)

def assert_cached_way(id):
    data = cache_query(ways=[id])
    if not data['ways'][str(id)]:
        raise AssertionError('way %d not found' % id)

def drop_test_schemas():
    conn = psycopg2.connect(**db_conf)
    cur = conn.cursor()
    cur.execute("DROP SCHEMA IF EXISTS %s CASCADE" % TEST_SCHEMA_IMPORT)
    cur.execute("DROP SCHEMA IF EXISTS %s CASCADE" % TEST_SCHEMA_PRODUCTION)
    cur.execute("DROP SCHEMA IF EXISTS %s CASCADE" % TEST_SCHEMA_BACKUP)
    conn.commit()

#######################################################################
def test_import():
    """Import succeeds"""
    drop_test_schemas()
    assert not table_exists('osm_roads', schema=TEST_SCHEMA_IMPORT)
    imposm3_import(db_conf, './build/test.pbf')
    assert table_exists('osm_roads', schema=TEST_SCHEMA_IMPORT)

def test_deploy():
    """Deploy succeeds"""
    assert not table_exists('osm_roads', schema=TEST_SCHEMA_PRODUCTION)
    imposm3_deploy(db_conf)
    assert table_exists('osm_roads', schema=TEST_SCHEMA_PRODUCTION)
    assert not table_exists('osm_roads', schema=TEST_SCHEMA_IMPORT)

#######################################################################

def test_imported_landusage():
    """Multipolygon relation is inserted"""
    assert_cached_node(1001, (13, 47.5))
    landusage_1001 = query_row(db_conf, 'osm_landusages', -1001)
    # point in polygon
    assert landusage_1001['geometry'].intersects(merc_point(13.4, 47.5))
    # hole in multipolygon relation
    assert not landusage_1001['geometry'].intersects(merc_point(14.75, 47.75))

def test_missing_nodes():
    """Cache does not contain nodes from previous imports"""
    assert_missing_node(10001)
    assert_missing_node(10002)
    place_10000 = query_row(db_conf, 'osm_places', 10000)
    assert place_10000['name'] == 'Foo', place_10000


def test_landusage_to_waterarea_1():
    """Parks inserted into landusages"""
    assert_cached_way(11001)
    assert_cached_way(12001)
    assert_cached_way(13001)

    assert not query_row(db_conf, 'osm_waterareas', 11001)
    assert not query_row(db_conf, 'osm_waterareas', -12001)
    assert not query_row(db_conf, 'osm_waterareas', -13001)

    assert not query_row(db_conf, 'osm_waterareas_gen0', 11001)
    assert not query_row(db_conf, 'osm_waterareas_gen0', -12001)
    assert not query_row(db_conf, 'osm_waterareas_gen0', -13001)

    assert not query_row(db_conf, 'osm_waterareas_gen1', 11001)
    assert not query_row(db_conf, 'osm_waterareas_gen1', -12001)
    assert not query_row(db_conf, 'osm_waterareas_gen1', -13001)

    assert query_row(db_conf, 'osm_landusages', 11001)['type'] == 'park'
    assert query_row(db_conf, 'osm_landusages', -12001)['type'] == 'park'
    assert query_row(db_conf, 'osm_landusages', -13001)['type'] == 'park'

    assert query_row(db_conf, 'osm_landusages_gen0', 11001)['type'] == 'park'
    assert query_row(db_conf, 'osm_landusages_gen0', -12001)['type'] == 'park'
    assert query_row(db_conf, 'osm_landusages_gen0', -13001)['type'] == 'park'

    assert query_row(db_conf, 'osm_landusages_gen1', 11001)['type'] == 'park'
    assert query_row(db_conf, 'osm_landusages_gen1', -12001)['type'] == 'park'
    assert query_row(db_conf, 'osm_landusages_gen1', -13001)['type'] == 'park'


def test_changed_hole_tags_1():
    """Multipolygon relation with untagged hole"""
    assert_cached_way(14001)
    assert_cached_way(14011)

    assert not query_row(db_conf, 'osm_waterareas', 14011)
    assert not query_row(db_conf, 'osm_waterareas', -14011)
    assert query_row(db_conf, 'osm_landusages', -14001)['type'] == 'park'

def test_split_outer_multipolygon_way_1():
    """Single outer way of multipolygon was inserted."""
    park_15001 = query_row(db_conf, 'osm_landusages', -15001)
    assert park_15001['type'] == 'park'
    assert_almost_equal(park_15001['geometry'].area, 9816216452, -1)
    assert query_row(db_conf, 'osm_roads', 15002) == None

def test_merge_outer_multipolygon_way_1():
    """Splitted outer way of multipolygon was inserted."""
    park_16001 = query_row(db_conf, 'osm_landusages', -16001)
    assert park_16001['type'] == 'park'
    assert_almost_equal(park_16001['geometry'].area, 12779350582, -1)
    assert query_row(db_conf, 'osm_roads', 16002)['type'] == 'residential'

def test_broken_multipolygon_ways():
    """MultiPolygons with broken outer ways are handled."""
    # outer way does not merge (17002 has one node)
    assert query_row(db_conf, 'osm_landusages', -17001) == None
    assert query_row(db_conf, 'osm_roads', 17001)['type'] == 'residential'
    assert query_row(db_conf, 'osm_roads', 17002) == None

    # outer way does not merge (17102 has no nodes)
    assert query_row(db_conf, 'osm_landusages', -17101) == None
    assert query_row(db_conf, 'osm_roads', 17101)['type'] == 'residential'
    assert query_row(db_conf, 'osm_roads', 17102) == None

def test_node_way_ref_after_delete_1():
    """Nodes refereces way"""
    data = cache_query(nodes=[20001, 20002], deps=True)
    assert '20001' in data['nodes']['20001']['ways']
    assert '20001' in data['nodes']['20002']['ways']
    assert query_row(db_conf, 'osm_roads', 20001)['type'] == 'residential'
    assert query_row(db_conf, 'osm_barrierpoints', 20001)['type'] == 'block'

def test_way_rel_ref_after_delete_1():
    """Ways references relation"""
    data = cache_query(ways=[21001], deps=True)
    assert data['ways']['21001']['relations'].keys() == ['21001']
    assert query_row(db_conf, 'osm_roads', 21001)['type'] == 'residential'
    assert query_row(db_conf, 'osm_landusages', -21001)['type'] == 'park'

def test_relation_way_not_inserted():
    """Part of relation was inserted only once."""
    park = query_row(db_conf, 'osm_landusages', -9001)
    assert park['type'] == 'park'
    assert park['name'] == 'rel 9001'
    assert query_row(db_conf, 'osm_landusages', 9009) == None

    park = query_row(db_conf, 'osm_landusages', -9101)
    assert park['type'] == 'park'
    assert park['name'] == 'rel 9101'
    assert query_row(db_conf, 'osm_landusages', 9109) == None

    scrub = query_row(db_conf, 'osm_landusages', 9110)
    assert scrub['type'] == 'scrub'

def test_relation_ways_inserted():
    """Outer ways of multipolygon are inserted. """
    park = query_row(db_conf, 'osm_landusages', -9201)
    assert park['type'] == 'park'
    assert park['name'] == '9209'

    # outer ways of multipolygon stand for their own
    road = query_row(db_conf, 'osm_roads', 9209)
    assert road['type'] == 'secondary'
    assert road['name'] == '9209'
    road = query_row(db_conf, 'osm_roads', 9210)
    assert road['type'] == 'residential'
    assert road['name'] == '9210'

    park = query_row(db_conf, 'osm_landusages', -9301)
    assert park['type'] == 'park'
    assert park['name'] == '' # no name on relation

    # outer ways of multipolygon stand for their own
    road = query_row(db_conf, 'osm_roads', 9309)
    assert road['type'] == 'secondary'
    assert road['name'] == '9309'
    road = query_row(db_conf, 'osm_roads', 9310)
    assert road['type'] == 'residential'
    assert road['name'] == '9310'

def test_relation_way_inserted():
    """Part of relation was inserted twice."""
    park = query_row(db_conf, 'osm_landusages', -8001)
    assert park['type'] == 'park'
    assert park['name'] == 'rel 8001'
    assert query_row(db_conf, 'osm_roads', 8009)["type"] == 'residential'

def test_single_node_ways_not_inserted():
    """Ways with single/duplicate nodes are not inserted."""
    assert not query_row(db_conf, 'osm_roads', 30001)
    assert not query_row(db_conf, 'osm_roads', 30002)
    assert not query_row(db_conf, 'osm_roads', 30003)

def test_polygon_with_duplicate_nodes_is_valid():
    """Polygon with duplicate nodes is valid."""
    geom = query_row(db_conf, 'osm_landusages', 30005)['geometry']
    assert geom.is_valid
    assert len(geom.exterior.coords) == 4

def test_incomplete_polygons():
    """Non-closed/incomplete polygons are not inserted."""
    assert not query_row(db_conf, 'osm_landusages', 30004)
    assert not query_row(db_conf, 'osm_landusages', 30006)

def test_residential_to_secondary():
    """Residential road is not in roads_gen0/1."""
    assert query_row(db_conf, 'osm_roads', 40001)['type'] == 'residential'
    assert not query_row(db_conf, 'osm_roads_gen0', 40001)
    assert not query_row(db_conf, 'osm_roads_gen1', 40001)

def test_relation_before_remove():
    """Relation and way is inserted."""
    assert query_row(db_conf, 'osm_buildings', 50011)['type'] == 'yes'
    assert query_row(db_conf, 'osm_landusages', -50021)['type'] == 'park'

def test_relation_without_tags():
    """Relation without tags is inserted."""
    assert query_row(db_conf, 'osm_buildings', 50111) == None
    assert query_row(db_conf, 'osm_buildings', -50121)['type'] == 'yes'

def test_duplicate_ids():
    """Relation/way with same ID is inserted."""
    assert query_row(db_conf, 'osm_buildings', 51001)['type'] == 'way'
    assert query_row(db_conf, 'osm_buildings', -51001)['type'] == 'mp'
    assert query_row(db_conf, 'osm_buildings', 51011)['type'] == 'way'
    assert query_row(db_conf, 'osm_buildings', -51011)['type'] == 'mp'

def test_generalized_banana_polygon_is_valid():
    """Generalized polygons are valid."""
    park = query_row(db_conf, 'osm_landusages', 7101)
    # geometry is not valid
    assert not park['geometry'].is_valid, park
    park = query_row(db_conf, 'osm_landusages_gen0', 7101)
    # but simplified geometies are valid
    assert park['geometry'].is_valid, park
    park = query_row(db_conf, 'osm_landusages_gen1', 7101)
    assert park['geometry'].is_valid, park

def test_generalized_linestring_is_valid():
    """Generalized linestring is valid."""
    road = query_row(db_conf, 'osm_roads', 7201)
    # geometry is not simple, but valid
    # check that geometry 'survives' simplification
    assert not road['geometry'].is_simple, road['geometry'].wkt
    assert road['geometry'].is_valid, road['geometry'].wkt
    assert road['geometry'].length > 1000000
    road = query_row(db_conf, 'osm_roads_gen0', 7201)
    # but simplified geometies are simple
    assert road['geometry'].is_valid, road['geometry'].wkt
    assert road['geometry'].length > 1000000
    road = query_row(db_conf, 'osm_roads_gen1', 7201)
    assert road['geometry'].is_valid, road['geometry'].wkt
    assert road['geometry'].length > 1000000


#######################################################################
def test_update():
    """Diff import applies"""
    imposm3_update(db_conf, './build/test.osc.gz')
#######################################################################

def test_updated_landusage():
    """Multipolygon relation was modified"""
    assert_cached_node(1001, (13.5, 47.5))
    landusage_1001 = query_row(db_conf, 'osm_landusages', -1001)
    # point not in polygon after update
    assert not landusage_1001['geometry'].intersects(merc_point(13.4, 47.5))

def test_partial_delete():
    """Deleted relation but nodes are still cached"""
    assert_cached_node(2001)
    assert_cached_way(2001)
    assert_cached_way(2002)
    assert not query_row(db_conf, 'osm_landusages', -2001)
    assert not query_row(db_conf, 'osm_landusages', 2001)

def test_updated_nodes():
    """Nodes were added, modified or deleted"""
    assert_missing_node(10000)
    assert_cached_node(10001, (10.0, 40.0))
    assert_cached_node(10002, (10.1, 40.0))
    place_10001 = query_row(db_conf, 'osm_places', 10001)
    assert place_10001['name'] == 'Bar', place_10001
    place_10002 = query_row(db_conf, 'osm_places', 10002)
    assert place_10002['name'] == 'Baz', place_10002

def test_landusage_to_waterarea_2():
    """Parks converted to water moved from landusages to waterareas"""
    assert_cached_way(11001)
    assert_cached_way(12001)
    assert_cached_way(13001)

    assert not query_row(db_conf, 'osm_landusages', 11001)
    assert not query_row(db_conf, 'osm_landusages', -12001)
    assert not query_row(db_conf, 'osm_landusages', -13001)

    assert not query_row(db_conf, 'osm_landusages_gen0', 11001)
    assert not query_row(db_conf, 'osm_landusages_gen0', -12001)
    assert not query_row(db_conf, 'osm_landusages_gen0', -13001)

    assert not query_row(db_conf, 'osm_landusages_gen1', 11001)
    assert not query_row(db_conf, 'osm_landusages_gen1', -12001)
    assert not query_row(db_conf, 'osm_landusages_gen1', -13001)

    assert query_row(db_conf, 'osm_waterareas', 11001)['type'] == 'water'
    assert query_row(db_conf, 'osm_waterareas', -12001)['type'] == 'water'
    assert query_row(db_conf, 'osm_waterareas', -13001)['type'] == 'water'

    assert query_row(db_conf, 'osm_waterareas_gen0', 11001)['type'] == 'water'
    assert query_row(db_conf, 'osm_waterareas_gen0', -12001)['type'] == 'water'
    assert query_row(db_conf, 'osm_waterareas_gen0', -13001)['type'] == 'water'

    assert query_row(db_conf, 'osm_waterareas_gen1', 11001)['type'] == 'water'
    assert query_row(db_conf, 'osm_waterareas_gen1', -12001)['type'] == 'water'
    assert query_row(db_conf, 'osm_waterareas_gen1', -13001)['type'] == 'water'

def test_changed_hole_tags_2():
    """Newly tagged hole is inserted"""
    assert_cached_way(14001)
    assert_cached_way(14011)

    assert query_row(db_conf, 'osm_waterareas', 14011)['type'] == 'water'
    assert query_row(db_conf, 'osm_landusages', -14001)['type'] == 'park'
    assert_almost_equal(query_row(db_conf, 'osm_waterareas', 14011)['geometry'].area, 26672000000, -6)
    assert_almost_equal(query_row(db_conf, 'osm_landusages', -14001)['geometry'].area, 10373600000, -6)

def test_split_outer_multipolygon_way_2():
    """Splitted outer way of multipolygon was inserted"""
    data = cache_query(ways=[15001, 15002], deps=True)
    assert data['ways']['15001']['relations'].keys() == ['15001']
    assert data['ways']['15002']['relations'].keys() == ['15001']

    assert query_row(db_conf, 'osm_landusages', 15001) == None
    park_15001 = query_row(db_conf, 'osm_landusages', -15001)
    assert park_15001['type'] == 'park'
    assert_almost_equal(park_15001['geometry'].area, 9816216452, -1)
    assert query_row(db_conf, 'osm_roads', 15002)['type'] == 'residential'

def test_merge_outer_multipolygon_way_2():
    """Merged outer way of multipolygon was inserted"""
    data = cache_query(ways=[16001, 16002], deps=True)
    assert data['ways']['16001']['relations'].keys() == ['16001']
    assert data['ways']['16002'] == None

    data = cache_query(relations=[16001], full=True)
    assert sorted(data['relations']['16001']['ways'].keys()) == ['16001', '16011']

    assert query_row(db_conf, 'osm_landusages', 16001) == None
    park_16001 = query_row(db_conf, 'osm_landusages', -16001)
    assert park_16001['type'] == 'park'
    assert_almost_equal(park_16001['geometry'].area, 12779350582, -1)
    assert query_row(db_conf, 'osm_roads', 16002) == None

def test_node_way_ref_after_delete_2():
    """Node does not referece deleted way"""
    data = cache_query(nodes=[20001, 20002], deps=True)
    assert 'ways' not in data['nodes']['20001']
    assert data['nodes']['20002'] == None
    assert query_row(db_conf, 'osm_roads', 20001) == None
    assert query_row(db_conf, 'osm_barrierpoints', 20001)['type'] == 'block'

def test_way_rel_ref_after_delete_2():
    """Way does not referece deleted relation"""
    data = cache_query(ways=[21001], deps=True)
    assert 'relations' not in data['ways']['21001']
    assert query_row(db_conf, 'osm_roads', 21001)['type'] == 'residential'
    assert query_row(db_conf, 'osm_landusages', 21001) == None
    assert query_row(db_conf, 'osm_landusages', -21001) == None

def test_residential_to_secondary2():
    """New secondary (from residential) is now in roads_gen0/1."""
    assert query_row(db_conf, 'osm_roads', 40001)['type'] == 'secondary'
    assert query_row(db_conf, 'osm_roads_gen0', 40001)['type'] == 'secondary'
    assert query_row(db_conf, 'osm_roads_gen1', 40001)['type'] == 'secondary'

def test_relation_after_remove():
    """Relation is deleted and way is still present."""
    assert query_row(db_conf, 'osm_buildings', 50011)['type'] == 'yes'
    assert query_row(db_conf, 'osm_landusages', 50021) == None
    assert query_row(db_conf, 'osm_landusages', -50021) == None

def test_relation_without_tags2():
    """Relation without tags is removed."""
    cache_query(ways=[50111], deps=True)
    assert cache_query(relations=[50121], deps=True)['relations']["50121"] == None

    assert query_row(db_conf, 'osm_buildings', 50111)['type'] == 'yes'
    assert query_row(db_conf, 'osm_buildings', 50121) == None
    assert query_row(db_conf, 'osm_buildings', -50121) == None

def test_duplicate_ids2():
    """Only relation/way with same ID was deleted."""
    assert query_row(db_conf, 'osm_buildings', 51001)['type'] == 'way'
    assert query_row(db_conf, 'osm_buildings', -51001) == None
    assert query_row(db_conf, 'osm_buildings', -51011)['type'] == 'mp'
    assert query_row(db_conf, 'osm_buildings', 51011) == None

#######################################################################
def test_deploy_and_revert_deploy():
    """Revert deploy succeeds"""
    assert not table_exists('osm_roads', schema=TEST_SCHEMA_IMPORT)
    assert table_exists('osm_roads', schema=TEST_SCHEMA_PRODUCTION)
    assert not table_exists('osm_roads', schema=TEST_SCHEMA_BACKUP)

    # import again to have a new import schema
    imposm3_import(db_conf, './build/test.pbf')
    assert table_exists('osm_roads', schema=TEST_SCHEMA_IMPORT)

    imposm3_deploy(db_conf)
    assert not table_exists('osm_roads', schema=TEST_SCHEMA_IMPORT)
    assert table_exists('osm_roads', schema=TEST_SCHEMA_PRODUCTION)
    assert table_exists('osm_roads', schema=TEST_SCHEMA_BACKUP)

    imposm3_revert_deploy(db_conf)
    assert table_exists('osm_roads', schema=TEST_SCHEMA_IMPORT)
    assert table_exists('osm_roads', schema=TEST_SCHEMA_PRODUCTION)
    assert not table_exists('osm_roads', schema=TEST_SCHEMA_BACKUP)

def test_remove_backup():
    """Remove backup succeeds"""
    assert table_exists('osm_roads', schema=TEST_SCHEMA_IMPORT)
    assert table_exists('osm_roads', schema=TEST_SCHEMA_PRODUCTION)
    assert not table_exists('osm_roads', schema=TEST_SCHEMA_BACKUP)

    imposm3_deploy(db_conf)

    assert not table_exists('osm_roads', schema=TEST_SCHEMA_IMPORT)
    assert table_exists('osm_roads', schema=TEST_SCHEMA_PRODUCTION)
    assert table_exists('osm_roads', schema=TEST_SCHEMA_BACKUP)

    imposm3_remove_backups(db_conf)

    assert not table_exists('osm_roads', schema=TEST_SCHEMA_IMPORT)
    assert table_exists('osm_roads', schema=TEST_SCHEMA_PRODUCTION)
    assert not table_exists('osm_roads', schema=TEST_SCHEMA_BACKUP)

