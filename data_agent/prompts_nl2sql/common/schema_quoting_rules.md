# Schema Quoting Rules

- PostgreSQL folds unquoted identifiers to lower case.
- Double-quote identifiers that contain uppercase letters, non-ASCII characters, spaces, or reserved words.
- Preserve table and column names exactly as exposed by the schema or semantic layer.
- Do not invent aliases for unavailable columns; refuse or ask for clarification when a requested field is not exposed.
