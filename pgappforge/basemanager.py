class BaseManager(object):
    """
    The parent class for all Managers
    """

    def __init__(self, appbuilder):
        self.appbuilder = appbuilder

    def register_views(self):
        """
        Register views and endpoints for this manager.
        
        This method is called during application initialization to register
        all views, endpoints, and menu items associated with this manager.
        Subclasses should override this method to implement their specific
        view registration logic.
        
        Note:
            This is an abstract method that should be implemented by subclasses.
            The default implementation is a no-op.
            
        Example:
            class MyManager(BaseManager):
                def register_views(self):
                    self.appbuilder.add_view(MyView, "My View", category="Tools")
        """
        pass  # pragma: no cover

    def pre_process(self):
        """
        Execute pre-processing tasks before manager initialization.
        
        This method is called before the manager is fully initialized and
        before views are registered. Use this method to perform setup tasks
        that need to happen early in the initialization process.
        
        Note:
            This is an abstract method that should be implemented by subclasses
            if pre-processing is needed. The default implementation is a no-op.
            
        Example:
            class MyManager(BaseManager):
                def pre_process(self):
                    self.setup_database_connections()
                    self.initialize_cache()
        """
        pass  # pragma: no cover

    def post_process(self):
        """
        Execute post-processing tasks after manager initialization.
        
        This method is called after the manager is fully initialized and
        after views are registered. Use this method to perform cleanup tasks
        or final setup that depends on the complete application state.
        
        Note:
            This is an abstract method that should be implemented by subclasses
            if post-processing is needed. The default implementation is a no-op.
            
        Example:
            class MyManager(BaseManager):
                def post_process(self):
                    self.validate_configuration()
                    self.start_background_tasks()
        """
        pass  # pragma: no cover
