-- Polsby-Popper test of compactness
CREATE OR REPLACE FUNCTION compactness(geom GEOMETRY) RETURNS FLOAT
AS 'SELECT 4 * PI() * ST_Area(geom) / power(ST_Perimeter(geom), 2)'
LANGUAGE SQL IMMUTABLE
RETURNS NULL ON NULL INPUT;

CREATE OR REPLACE FUNCTION max_dimension(geom GEOMETRY) RETURNS FLOAT
AS 'SELECT ST_MaxDistance(geom, geom)'
LANGUAGE SQL IMMUTABLE
RETURNS NULL ON NULL INPUT;

CREATE MATERIALIZED VIEW inspire_filtered AS
	SELECT ogc_fid, inspireid, wkb_geometry
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
					(COALESCE(ST_Area(ST_Difference(b.wkb_geometry, a.wkb_geometry)), 0) < 1 AND b.ogc_fid < a.ogc_fid)
					OR compactness(a.wkb_geometry) < compactness(b.wkb_geometry)
				)
				AND b.ogc_fid != a.ogc_fid
		);


DROP MATERIALIZED VIEW split_buildings;
CREATE MATERIALIZED VIEW split_buildings AS
	SELECT DISTINCT ON (inspireid) inspireid, geometry FROM
		(SELECT inspire.inspireid,
			(ST_Dump(ST_Buffer(ST_Intersection(inspire.wkb_geometry, buildings.geometry), 0.0))).geom AS geometry
		FROM inspire_filtered AS inspire, buildings
		WHERE ST_Intersects(inspire.wkb_geometry, buildings.geometry)
			AND not ST_IsEmpty(ST_Buffer(ST_Intersection(inspire.wkb_geometry, buildings.geometry), 0.0))
		) a
		WHERE ST_Area(geometry) > 10
		ORDER BY inspireid, ST_Area(geometry) DESC;


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
