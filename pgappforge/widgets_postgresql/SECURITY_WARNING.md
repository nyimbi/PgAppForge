# CRITICAL SECURITY WARNING - PostgreSQL Tree Widget

## SQL Injection Vulnerabilities Identified

The `tree_widget.py` file contains **CRITICAL SQL injection vulnerabilities** in the JavaScript code that generates dynamic SQL statements.

### Vulnerable Code Locations:

1. **Line ~insertStmt**: Direct concatenation of table and field names into INSERT statements
2. **Line ~insertStatement**: LTREE INSERT statements without validation
3. **Line ~generateSQLSelectExport**: Dynamic SELECT query building with user input
4. **Line ~values.map**: Direct concatenation of user data into SQL VALUES clauses

### Immediate Actions Required:

1. **DISABLE the PostgreSQL Tree Widget** in production until fixes are applied
2. **Implement SQL injection prevention methods** (see suggested fixes below)
3. **Use parameterized queries** or proper ORM methods instead of string concatenation
4. **Validate and sanitize all user inputs** before SQL generation

### Suggested Security Fixes:

```javascript
// Add these security methods to the widget:
sanitizeSQLIdentifier: function(identifier) {
    if (!identifier || typeof identifier !== 'string') {
        throw new Error('Invalid SQL identifier');
    }
    // Only allow alphanumeric and underscore
    let sanitized = identifier.replace(/[^a-zA-Z0-9_]/g, '');
    if (/^[0-9]/.test(sanitized)) sanitized = 'field_' + sanitized;
    return sanitized.substring(0, 64);
},

escapeSQLString: function(value) {
    if (!value) return 'NULL';
    return "'" + String(value).replace(/'/g, "''") + "'";
},

validateLTreePath: function(path) {
    if (!path) return null;
    const ltreePattern = /^[a-zA-Z0-9_]+(\.[a-zA-Z0-9_]+)*$/;
    return ltreePattern.test(path) ? path : null;
}
```

### Replace All Vulnerable Patterns:

- `'INSERT INTO ' + tableName` → `'INSERT INTO ' + this.sanitizeSQLIdentifier(tableName)`
- `"'" + userInput + "'"` → `this.escapeSQLString(userInput)`
- Direct path concatenation → `this.validateLTreePath(path)`

### Risk Level: **CRITICAL**

These vulnerabilities allow attackers to:
- Execute arbitrary SQL commands
- Access unauthorized data
- Modify or delete database contents
- Potentially gain system access

**DO NOT USE THIS WIDGET IN PRODUCTION** until all SQL injection vulnerabilities are fixed.