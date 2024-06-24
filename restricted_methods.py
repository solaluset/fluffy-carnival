class RestrictedMethodError(Exception):
    pass


def _create_restrictor():
    try:
        from sys import _getframe
    except ImportError:

        def _getframe(depth=0):
            try:
                raise Exception
            except Exception as e:
                frame = e.__traceback__.tb_frame.f_back
                for _ in range(depth):
                    frame = frame.f_back
                return frame

    import builtins
    from builtins import __build_class__ as default_build_class
    import functools
    from inspect import isroutine

    func_to_class = {}
    class_to_methods = {}

    def unwrap(func, hide):
        f = func
        while hasattr(f, "__wrapped__"):
            func, f = f, f.__wrapped__
            if f in hide:
                del func.__wrapped__
        return f

    def collect_codes(cls, hide):
        funcs = []
        for i in dir(cls):
            i = getattr(cls, i)
            if isinstance(i, property):
                funcs.extend(
                    map(lambda f: unwrap(f, hide), (i.fget, i.fset, i.fdel))
                )
            elif isroutine(i):
                funcs.append(unwrap(i, hide))
        return [f.__code__ for f in funcs if hasattr(f, "__code__")]

    @functools.wraps(default_build_class)
    def build_class(func, name, *bases, **kwargs):
        cls = default_build_class(func, name, *bases, **kwargs)
        if cls.__qualname__ in class_to_methods:
            funcs = class_to_methods.pop(cls.__qualname__)
            for func in funcs:
                func_to_class[func] = cls
            codes = collect_codes(cls, funcs)
            class_to_methods[cls] = (codes, codes.copy())
        for base_cls in cls.__bases__:
            if base_cls in class_to_methods:
                codes = collect_codes(cls, ())
                class_to_methods[base_cls][1].extend(codes)
        return cls

    builtins.__build_class__ = build_class

    def restrictor(func, type_):
        path, sep, name = func.__qualname__.rpartition("<locals>.")
        class_ = name.rpartition(".")[0]
        if not class_:
            raise ValueError(
                "Cannot restrict function not associated with class"
            )

        class_to_methods.setdefault("".join((path, sep, class_)), []).append(
            func
        )

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            code = _getframe(1).f_code
            cls = func_to_class[func]
            if any(code is c for c in class_to_methods[cls][type_]):
                return func(*args, **kwargs)
            typ = "private" if type_ == 0 else "protected"
            raise RestrictedMethodError(
                f"Cannot call {typ} method {func!r}"
                f" from caller {code.co_qualname!r}"
            )

        return wrapper

    return restrictor


_restrictor = _create_restrictor()


def protected(func):
    return _restrictor(func, 1)


def private(func):
    return _restrictor(func, 0)


def test_restricted():
    from functools import lru_cache

    import pytest

    class A:
        @private
        def a(self):
            return 1

        @protected
        def b(self):
            return 2

        @lru_cache()
        def c(self):
            return self.a() + self.b()

    with pytest.raises(RestrictedMethodError):
        A().a()
    with pytest.raises(RestrictedMethodError):
        A().b()
    with pytest.raises(AttributeError):
        A().a.__wrapped__()

    A().c()

    class B(A):
        def a(self):
            return super().a()

        def b(self):
            return super().b()

    with pytest.raises(RestrictedMethodError):
        B().a()

    B().b()
    with pytest.raises(RestrictedMethodError):
        B().c()

    # test property
    class A:
        _a = 1

        @property
        def a(self):
            return self._a

        @a.setter
        @private
        def a(self, value):
            self._a = value

        def set_a(self, value):
            self.a = value

    a = A()
    a.a
    with pytest.raises(RestrictedMethodError):
        a.a = 2
    a.set_a(2)
