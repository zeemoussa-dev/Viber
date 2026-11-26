-- A rule can cover several components. `components` is the list (empty = the whole project). `scope` stays as its
-- readable form ('project' or 'component:a,b'), and a trigger keeps the two in step however a row is written
-- (API, importer or SQL), so they can never disagree.
ALTER TABLE rule ADD COLUMN components text[] NOT NULL DEFAULT '{}';

CREATE FUNCTION rule_reach_sync() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF cardinality(NEW.components) = 0 AND NEW.scope LIKE 'component:%' THEN
            NEW.components := string_to_array(substr(NEW.scope, 11), ',');
        END IF;
    ELSIF NEW.components IS NOT DISTINCT FROM OLD.components AND NEW.scope IS DISTINCT FROM OLD.scope THEN
        NEW.components := CASE WHEN NEW.scope LIKE 'component:%' THEN string_to_array(substr(NEW.scope, 11), ',') ELSE '{}'::text[] END;
    END IF;
    NEW.components := COALESCE((SELECT array_agg(DISTINCT btrim(c) ORDER BY btrim(c)) FROM unnest(NEW.components) AS c WHERE btrim(c) <> ''), '{}');
    IF cardinality(NEW.components) > 0 THEN
        NEW.scope := 'component:' || array_to_string(NEW.components, ',');
    ELSIF NEW.scope LIKE 'component:%' THEN
        NEW.scope := 'project';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER rule_reach BEFORE INSERT OR UPDATE ON rule FOR EACH ROW EXECUTE FUNCTION rule_reach_sync();

UPDATE rule SET components = string_to_array(substr(scope, 11), ',') WHERE scope LIKE 'component:%';
CREATE INDEX rule_components ON rule USING gin (components);
