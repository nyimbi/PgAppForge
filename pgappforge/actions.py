class ActionItem(object):
    """
    Represents an action that can be performed on model records.
    
    Actions are used to provide custom functionality in list views,
    allowing users to perform bulk operations or single record operations.
    """
    
    def __init__(self, name, text, confirmation=None, icon=None, multiple=True, single=True, func=None):
        """
        Initialize an action item.
        
        Args:
            name: Unique name for the action
            text: Display text for the action button
            confirmation: Optional confirmation message to show before executing
            icon: Optional icon CSS class for the action button
            multiple: Whether action can be performed on multiple records
            single: Whether action can be performed on a single record
            func: Function to execute when action is triggered
        """
        self.name = name
        self.text = text or name
        self.confirmation = confirmation
        self.icon = icon
        self.multiple = multiple
        self.single = single
        self.func = func

    def __repr__(self):
        """String representation of the action item."""
        return "Action name:%s; text:%s; confirmation:%s; func:%s;" % (
            self.name,
            self.text,
            self.confirmation,
            self.func.__name__ if self.func else None,
        )


def action(name, text, confirmation=None, icon=None, multiple=True, single=True):
    """
    Decorator to define an action on a model view.
    
    Args:
        name: Unique name for the action
        text: Display text for the action button
        confirmation: Optional confirmation message
        icon: Optional icon CSS class
        multiple: Whether action supports multiple records
        single: Whether action supports single records
        
    Returns:
        Decorated function that becomes an action
        
    Example:
        @action("approve", "Approve Records", "Are you sure?")
        def approve_records(self, items):
            for item in items:
                item.status = "approved"
            return "Records approved successfully"
    """
    def wrap(f):
        if not hasattr(f, "_action"):
            f._action = ActionItem(
                name=name,
                text=text,
                confirmation=confirmation,
                icon=icon,
                multiple=multiple,
                single=single,
                func=f
            )
        return f
    return wrap