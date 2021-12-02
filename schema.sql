-- Polsby-Popper test of compactness
CREATE OR REPLACE FUNCTION compactness(geom GEOMETRY) RETURNS FLOAT
AS 'SELECT 4 * PI() * ST_Area(geom) / power(ST_Perimeter(geom), 2)'
LANGUAGE SQL IMMUTABLE
PARALLEL SAFE
RETURNS NULL ON NULL INPUT;

CREATE OR REPLACE FUNCTION max_dimension(geom GEOMETRY) RETURNS FLOAT
AS 'SELECT ST_MaxDistance(geom, geom)'
LANGUAGE SQL IMMUTABLE
PARALLEL SAFE
RETURNS NULL ON NULL INPUT;

-- 5 invalid geometries in INSPIRE as of 2021-10-07. Just delete them.
DELETE FROM inspire WHERE NOT ST_IsValid(wkb_geometry);
-- 2 invalid geometries in Scottish INSPIRE as of 2021-11-29
DELETE FROM inspire_scotland WHERE NOT ST_IsValid(wkb_geometry);

-- Scotland has multipolygons, England doesn't, unify the types or it causes problems with indexes.
-- (this is a bit slow, can we do this as part of the import process?)
alter table inspire_england alter wkb_geometry type geometry(Geometry,27700);
alter table inspire_scotland alter wkb_geometry type geometry(Geometry,27700);

CREATE OR REPLACE VIEW inspire AS
	SELECT inspireid::text, wkb_geometry AS wkb_geometry FROM inspire_england
	UNION ALL
	SELECT inspireid::text, wkb_geometry AS wkb_geometry FROM inspire_scotland;


CREATE MATERIALIZED VIEW inspire_filtered AS SELECT inspireid, wkb_geometry::GEOMETRY(Geometry, 27700)
	FROM inspire AS a
	WHERE ST_AREA(wkb_geometry) < 10000
		AND ST_Area(wkb_geometry) > 45
		AND max_dimension(wkb_geometry) < 150
		AND NOT EXISTS (
			SELECT 1 FROM inspire AS b
				WHERE ST_Intersects(a.wkb_geometry, b.wkb_geometry)
				AND ST_Area(ST_Intersection(a.wkb_geometry, b.wkb_geometry)) > 1
				AND ST_Area(b.wkb_geometry) < 10000
				AND ST_Area(b.wkb_geometry) > 45
				AND (
					(COALESCE(ST_Area(ST_Difference(b.wkb_geometry, a.wkb_geometry)), 0) < 1 AND b.inspireid < a.inspireid)
					OR compactness(a.wkb_geometry) < compactness(b.wkb_geometry)
				)
				AND b.inspireid != a.inspireid
		);


DROP MATERIALIZED VIEW split_buildings;
CREATE MATERIALIZED VIEW split_buildings AS SELECT DISTINCT ON (inspireid) inspireid, geometry::GEOMETRY(Polygon, 27700) FROM
		(SELECT inspire.inspireid,
			(ST_Dump(ST_Buffer(ST_Intersection(inspire.wkb_geometry, buildings.wkb_geometry), 0.0))).geom AS geometry
		FROM inspire_filtered AS inspire, buildings
		WHERE ST_Intersects(inspire.wkb_geometry, buildings.wkb_geometry)
			AND not ST_IsEmpty(ST_Buffer(ST_Intersection(inspire.wkb_geometry, buildings.wkb_geometry), 0.0))
		) a
		WHERE ST_Area(geometry) > 10
		ORDER BY inspireid, ST_Area(geometry) DESC;



CREATE INDEX split_buildings_geom ON split_buildings USING gist(geometry);

CREATE OR REPLACE VIEW split_building_centroids AS 
	SELECT inspireid, count(uprn.uprn) AS uprn_count, ST_PointOnSurface(geometry) AS geometry
	FROM split_buildings, uprn
	WHERE ST_Contains(geometry, uprn.geom)
	GROUP BY inspireid, split_buildings.geometry;


CREATE MATERIALIZED VIEW uprn_buildings AS
	SELECT row_number() OVER () AS id, count(uprn.uprn) AS urpn_count, uprn.geom AS geometry
	FROM uprn, buildings
	WHERE ST_Contains(buildings.geometry, uprn.geom)
	GROUP BY uprn.geom;
