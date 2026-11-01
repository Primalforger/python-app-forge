# Table Designer

The desktop Table Designer uses a column grid rather than requiring users to edit a JSON
document. Each row defines a column key and its data type. Use **Add column** to append a
new column, edit its key in the first cell, and choose a type from the second cell. Select
a row and use **Remove selected** to delete it.

Supported types are `text`, `number`, `date`, `bool`, and `category`. Column keys
must be lowercase Python-style identifiers. The designer validates the complete definition
through the same backend used by `forge table design`, then generates the Python model
configuration for `forge.advanced-table`.

The initial definition's default sort, filter, pagination, and CSV export settings remain
in place while columns are edited. Invalid definitions are reported by the shared validator.
