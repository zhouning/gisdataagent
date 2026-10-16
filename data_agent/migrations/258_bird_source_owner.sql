-- BIRD benchmark sources are private to their owner unless an admin accesses them.
ALTER TABLE agent_bird_databases
    ADD COLUMN owner_username TEXT NOT NULL DEFAULT 'bird_benchmark';
