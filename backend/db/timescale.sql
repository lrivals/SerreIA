-- TimescaleDB part of the schema (docs/09 §7), applied by backend.db.session.init_db
-- after create_all on PostgreSQL only. Idempotent: run at every start.
-- One statement per ';' (no DO blocks: the file is split on ';').

CREATE EXTENSION IF NOT EXISTS timescaledb;

SELECT create_hypertable('mesure', by_range('ts', INTERVAL '7 days'), if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('vision_resultat', by_range('ts', INTERVAL '30 days'), if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('etat_actionneur', by_range('ts', INTERVAL '30 days'), if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('commande', by_range('ts', INTERVAL '30 days'), if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('alerte', by_range('ts', INTERVAL '30 days'), if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('noeud_status', by_range('ts', INTERVAL '30 days'), if_not_exists => TRUE, migrate_data => TRUE);
