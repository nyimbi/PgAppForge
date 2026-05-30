from typing import Any, Callable, Dict, List


def before_request(
    hook: Callable[[], Any] = None, only: List[str] = None
) -> Callable[..., Any]:
    """
    This decorator provides a way to hook into the request
    lifecycle by enqueueing methods to be invoked before
    each handler in the view. If the method returns a value
    other than :code:`None`, then that value will be returned
    to the client. If invoked with the :code:`only` kwarg,
    the hook will only be invoked for the given list of
    handler methods.

    Examples::

        class MyFeature(ModelView)

            @before_request
            def ensure_feature_is_enabled(self):
                if self.feature_is_disabled:
                    return self.response_404()
                return None

            # etc...


        class MyView(ModelRestAPI):

            @before_request(only=["create", "update", "delete"])
            def ensure_write_mode_enabled(self):
                if self.read_only:
                    return self.response_400()
                return None

            # etc...

    :param hook:
        A callable to be invoked before handlers in the class. If the
        hook returns :code:`None`, then the request proceeds and the
        handler is invoked. If it returns something other than :code:`None`,
        then execution halts and that value is returned to the client.
    :param only:
        An optional list of the names of handler methods. If present,
        :code:`hook` will only be invoked before the handlers specified
        in the list. If absent, :code:`hook` will be invoked for before
        all handlers in the class.
    """

    def wrap(hook: Callable[[], Any]) -> Callable[[], Any]:
        """
        Internal wrapper function to mark a function as a before-request hook.
        
        Args:
            hook: The function to mark as a hook
            
        Returns:
            The wrapped hook function with metadata attributes
        """
        hook._before_request_hook = True
        hook._before_request_only = only
        return hook

    return wrap if hook is None else wrap(hook)


def wrap_route_handler_with_hooks(
    handler_name: str,
    handler: Callable[..., Any],
    before_request_hooks: List[Callable[[], Any]],
) -> Callable[..., Any]:
    """
    Wrap a route handler with applicable before-request hooks.
    
    This function creates a new handler that executes before-request hooks
    before calling the original handler. If any hook returns a non-None
    value, that value is returned instead of calling the original handler.
    
    Args:
        handler_name: Name of the handler being wrapped
        handler: The original route handler function
        before_request_hooks: List of hook functions to apply
        
    Returns:
        A new handler function that executes hooks before the original handler
        
    Note:
        Only hooks that are applicable to the named handler will be executed.
        Hooks can specify which handlers they apply to using the 'only' parameter.
    """
    applicable_hooks = []
    for hook in before_request_hooks:
        only = hook._before_request_only
        applicable_hook = only is None or handler_name in only
        if applicable_hook:
            applicable_hooks.append(hook)

    if not applicable_hooks:
        return handler

    def wrapped_handler(*args: List[Any], **kwargs: Dict[str, Any]) -> Any:
        """
        Execute applicable hooks before calling the original handler.
        
        Args:
            *args: Positional arguments for the original handler
            **kwargs: Keyword arguments for the original handler
            
        Returns:
            Result from the first hook that returns non-None, or
            result from the original handler if no hooks intercept
        """
        for hook in applicable_hooks:
            result = hook()
            if result is not None:
                return result
        return handler(*args, **kwargs)

    return wrapped_handler


def get_before_request_hooks(view_or_api_instance: Any) -> List[Callable[[], Any]]:
    """
    Extract all before-request hook methods from a view or API instance.
    
    This function inspects a view or API instance and returns a list of all
    methods that have been decorated with the @before_request decorator.
    These hooks will be executed before route handlers are called.
    
    Args:
        view_or_api_instance: The view or API instance to inspect for hooks
        
    Returns:
        List of callable hook functions found on the instance
        
    Example:
        class MyView(BaseView):
            @before_request
            def check_auth(self):
                if not current_user.is_authenticated:
                    return redirect('/login')
                    
        view = MyView()
        hooks = get_before_request_hooks(view)
        # hooks will contain [view.check_auth]
    """
    before_request_hooks = []
    for attr_name in dir(view_or_api_instance):
        attr = getattr(view_or_api_instance, attr_name)
        if hasattr(attr, "_before_request_hook") and attr._before_request_hook is True:
            before_request_hooks.append(attr)
    return before_request_hooks
