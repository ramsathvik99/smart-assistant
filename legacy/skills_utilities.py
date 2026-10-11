# -*- coding: utf-8 -*-
"""
Skills Utilities - Implementations for common skill functions needed by unified_command_router

Provides: tell_time, tell_date, solve_math, translate_text, etc.
"""

import logging
import re
import datetime
from typing import Optional

logger = logging.getLogger(__name__)

def tell_time() -> str:
    """Get current time"""
    try:
        now = datetime.datetime.now()
        time_str = now.strftime("%I:%M %p")  # 12-hour format with AM/PM
        return f"The current time is {time_str}."
    except Exception as e:
        logger.error(f"Error getting time: {e}")
        return "Unable to retrieve current time."

def tell_date() -> str:
    """Get current date"""
    try:
        now = datetime.datetime.now()
        date_str = now.strftime("%A, %B %d, %Y")  # e.g., "Monday, January 15, 2024"
        return f"Today is {date_str}."
    except Exception as e:
        logger.error(f"Error getting date: {e}")
        return "Unable to retrieve current date."

def _fmt(value) -> str:
    """Format a numeric result cleanly (no trailing .0 for integers)."""
    try:
        if isinstance(value, float) and value == int(value):
            return str(int(value))
        if isinstance(value, float):
            # Up to 10 significant figures, strip trailing zeros
            formatted = f"{value:.10g}"
            return formatted
        return str(value)
    except Exception:
        return str(value)


def _safe_eval(expr: str) -> Optional[float]:
    """
    Evaluate a mathematical expression string safely using only math functions.
    No access to builtins, imports, or any non-math symbols.
    """
    import math as _math
    _SAFE_NS = {
        "__builtins__": {},
        # Constants
        "pi": _math.pi,
        "e": _math.e,
        "tau": _math.tau,
        "inf": _math.inf,
        "phi": (1 + _math.sqrt(5)) / 2,
        # Basic functions
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "pow": pow,
        # Math functions
        "sqrt": _math.sqrt,
        "cbrt": lambda x: x ** (1 / 3) if x >= 0 else -((-x) ** (1 / 3)),
        "exp": _math.exp,
        "log": _math.log10,      # log() = log10 (common)
        "log10": _math.log10,
        "log2": _math.log2,
        "ln": _math.log,         # ln() = natural log
        "ceil": _math.ceil,
        "floor": _math.floor,
        "factorial": _math.factorial,
        # Trig (degrees)
        "sin": lambda x: _math.sin(_math.radians(x)),
        "cos": lambda x: _math.cos(_math.radians(x)),
        "tan": lambda x: _math.tan(_math.radians(x)),
        "asin": lambda x: _math.degrees(_math.asin(x)),
        "acos": lambda x: _math.degrees(_math.acos(x)),
        "atan": lambda x: _math.degrees(_math.atan(x)),
        # Trig (radians variants)
        "sinr": _math.sin,
        "cosr": _math.cos,
        "tanr": _math.tan,
        "gcd": _math.gcd,
        "lcm": _math.lcm if hasattr(_math, "lcm") else (lambda a, b: abs(a * b) // _math.gcd(a, b)),
        "hypot": _math.hypot,
        "degrees": _math.degrees,
        "radians": _math.radians,
        "comb": _math.comb,
        "perm": _math.perm,
    }
    try:
        import ast
        import operator

        _OP_MAP = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.FloorDiv: operator.floordiv,
            ast.Mod: operator.mod,
            ast.Pow: operator.pow,
            ast.USub: operator.neg,
            ast.UAdd: operator.pos,
        }

        def _eval_ast(node):
            if isinstance(node, ast.Expression):
                return _eval_ast(node.body)
            elif isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float, complex)):
                    return node.value
                raise ValueError(f"Disallowed constant: {node.value}")
            elif isinstance(node, ast.BinOp):
                left = _eval_ast(node.left)
                right = _eval_ast(node.right)
                op_fn = _OP_MAP.get(type(node.op))
                if op_fn is None:
                    raise ValueError(f"Disallowed operator: {type(node.op)}")
                return op_fn(left, right)
            elif isinstance(node, ast.UnaryOp):
                operand = _eval_ast(node.operand)
                op_fn = _OP_MAP.get(type(node.op))
                if op_fn is None:
                    raise ValueError(f"Disallowed unary operator: {type(node.op)}")
                return op_fn(operand)
            elif isinstance(node, ast.Name):
                if node.id in _SAFE_NS:
                    return _SAFE_NS[node.id]
                raise ValueError(f"Disallowed identifier: {node.id}")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in _SAFE_NS:
                    fn = _SAFE_NS[node.func.id]
                    if callable(fn):
                        args = [_eval_ast(a) for a in node.args]
                        return fn(*args)
                raise ValueError(f"Disallowed function call")
            raise ValueError(f"Disallowed AST element: {type(node)}")

        parsed_ast = ast.parse(expr, mode='eval')
        return _eval_ast(parsed_ast)
    except ZeroDivisionError:
        raise
    except Exception:
        return None


def solve_math(expression: str) -> Optional[str]:
    """
    Comprehensive math solver.

    Handles:
    - Basic arithmetic  (+, -, *, /, ^, **)
    - Percentages       ("15 percent of 200", "20% of 500", "percentage change")
    - Powers/roots      ("2 to the power of 10", "5 squared", "square root of 144")
    - Trigonometry      ("sin(45)", "cos 60 degrees", "tan 30")
    - Logarithms        ("log(1000)", "ln(e^2)", "log base 2 of 8")
    - Factorials        ("5!", "5 factorial", "factorial of 10")
    - Constants         (pi, e, phi)
    - Statistics        ("mean of 1,2,3,4,5", "median", "standard deviation")
    - Geometry          ("area of circle radius 5", "circumference", "volume of sphere")
    - Financial         ("simple interest / compound interest on ...")
    - GCD / LCM         ("GCD of 48 and 18")
    - Divisibility      ("is 17 prime", "factors of 36")
    - Symbolic solving  ("solve x^2 - 5x + 6 = 0") via sympy
    - Free-form eval    ("pi * 5^2", "sqrt(2) + log(100)")
    """
    import math as _math

    raw = expression.strip()
    text = raw.lower()

    # ── Strip filler phrases ────────────────────────────────────────────────
    for ph in ["please", "can you", "could you", "what's", "what is", "how much is",
               "how many is", "calculate", "compute", "evaluate", "find", "solve",
               "tell me", "give me", "show me", "determine", "work out"]:
        text = re.sub(r'\b' + re.escape(ph) + r'\b', ' ', text, flags=re.IGNORECASE)
    text = text.strip()

    # ── 1. Percentage ───────────────────────────────────────────────────────
    # "15 percent of 200" / "15% of 200"
    m = re.search(r'([\d.]+)\s*(?:percent|%)\s+of\s+([\d.]+)', text, re.IGNORECASE)
    if m:
        pct, base = float(m.group(1)), float(m.group(2))
        result = (pct / 100) * base
        return f"{pct}% of {_fmt(base)} = {_fmt(result)}"

    # "percentage change from X to Y"
    m = re.search(r'percentage\s+(?:change|increase|decrease|difference)\s+from\s+([\d.]+)\s+to\s+([\d.]+)', text)
    if m:
        old, new = float(m.group(1)), float(m.group(2))
        if old == 0:
            return "Cannot compute percentage change from zero."
        change = ((new - old) / abs(old)) * 100
        direction = "increase" if change >= 0 else "decrease"
        return f"Percentage {direction} from {_fmt(old)} to {_fmt(new)} = {_fmt(abs(change))} percent"

    # "X is what percent of Y"
    m = re.search(r'([\d.]+)\s+is\s+what\s+percent\s+of\s+([\d.]+)', text)
    if m:
        part, whole = float(m.group(1)), float(m.group(2))
        if whole == 0:
            return "Cannot divide by zero."
        pct = (part / whole) * 100
        return f"{_fmt(part)} is {_fmt(pct)}% of {_fmt(whole)}"

    # ── 2. Factorial ────────────────────────────────────────────────────────
    m = re.search(r'factorial\s+of\s+([\d]+)|([\d]+)\s+factorial|([\d]+)\s*!', text)
    if m:
        n = int(m.group(1) or m.group(2) or m.group(3))
        if n > 10000:
            return "Number too large for factorial."
        result = _math.factorial(n)
        return f"{n}! = {result}"

    # ── 3. GCD / LCM ────────────────────────────────────────────────────────
    m = re.search(r'\b(?:gcd|greatest\s+common\s+(?:divisor|factor))\s+of\s+([\d]+)\s+and\s+([\d]+)', text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return f"GCD({a}, {b}) = {_math.gcd(a, b)}"

    m = re.search(r'\b(?:lcm|least\s+common\s+multiple)\s+of\s+([\d]+)\s+and\s+([\d]+)', text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        lcm = abs(a * b) // _math.gcd(a, b)
        return f"LCM({a}, {b}) = {lcm}"

    # ── 4. Prime check ──────────────────────────────────────────────────────
    m = re.search(r'\bis\s+([\d]+)\s+(?:a\s+)?prime', text)
    if m:
        n = int(m.group(1))
        if n < 2:
            return f"{n} is not a prime number."
        is_prime = all(n % i != 0 for i in range(2, int(_math.sqrt(n)) + 1))
        return f"{n} is {'a prime' if is_prime else 'not a prime'} number."

    # ── 5. Factors ──────────────────────────────────────────────────────────
    m = re.search(r'\b(?:factors?|divisors?)\s+of\s+([\d]+)', text)
    if m:
        n = int(m.group(1))
        factors = sorted(set(
            f for i in range(1, int(_math.sqrt(n)) + 1) if n % i == 0
            for f in (i, n // i)
        ))
        return f"Factors of {n}: {', '.join(map(str, factors))}"

    # ── 6. Powers ("X to the power of Y", "X^Y", "X squared", "X cubed") ──
    m = re.search(r'([\d.]+)\s+to\s+the\s+(?:power\s+of|power)\s+([\d.]+)', text)
    if m:
        base, exp = float(m.group(1)), float(m.group(2))
        result = base ** exp
        return f"{_fmt(base)}^{_fmt(exp)} = {_fmt(result)}"

    m = re.search(r'([\d.]+)\s+squared', text)
    if m:
        n = float(m.group(1))
        return f"{_fmt(n)} squared = {_fmt(n ** 2)}"

    m = re.search(r'([\d.]+)\s+cubed', text)
    if m:
        n = float(m.group(1))
        return f"{_fmt(n)} cubed = {_fmt(n ** 3)}"

    # ── 7. Roots ────────────────────────────────────────────────────────────
    m = re.search(r'(?:square\s+root|sqrt)\s+(?:of\s+)?([\d.]+)', text)
    if m:
        n = float(m.group(1))
        result = _math.sqrt(n)
        return f"Square root of {_fmt(n)} = {_fmt(result)}"

    m = re.search(r'cube\s+root\s+(?:of\s+)?([\d.]+)', text)
    if m:
        n = float(m.group(1))
        result = n ** (1 / 3) if n >= 0 else -((-n) ** (1 / 3))
        return f"Cube root of {_fmt(n)} = {_fmt(result)}"

    m = re.search(r'([\d.]+)(?:th|st|nd|rd)?\s*root\s+of\s+([\d.]+)', text)
    if m:
        root_n, val = float(m.group(1)), float(m.group(2))
        result = val ** (1 / root_n)
        return f"{_fmt(root_n)}th root of {_fmt(val)} = {_fmt(result)}"

    # ── 8. Logarithms ───────────────────────────────────────────────────────
    m = re.search(r'\blog\s+base\s+([\d.]+)\s+of\s+([\d.]+)', text)
    if m:
        base, val = float(m.group(1)), float(m.group(2))
        result = _math.log(val, base)
        return f"log_{_fmt(base)}({_fmt(val)}) = {_fmt(result)}"

    m = re.search(r'\bnatural\s+log(?:arithm)?\s+(?:of\s+)?([\d.]+)', text)
    if m:
        val = float(m.group(1))
        return f"ln({_fmt(val)}) = {_fmt(_math.log(val))}"

    m = re.search(r'\bln\s*\(?\s*([\d.]+)\s*\)?', text)
    if m:
        val = float(m.group(1))
        return f"ln({_fmt(val)}) = {_fmt(_math.log(val))}"

    # ── 9. Trigonometry ─────────────────────────────────────────────────────
    for fn in ["sin", "cos", "tan", "asin", "acos", "atan"]:
        # "sin(45)", "sin of 45", "sin 45 degrees"
        m = re.search(rf'\b{fn}\s*\(?\s*([\d.]+)\s*(?:degrees?)?\s*\)?', text)
        if m:
            angle = float(m.group(1))
            if fn == "sin":
                result = _math.sin(_math.radians(angle))
            elif fn == "cos":
                result = _math.cos(_math.radians(angle))
            elif fn == "tan":
                result = _math.tan(_math.radians(angle))
            elif fn == "asin":
                result = _math.degrees(_math.asin(angle))
            elif fn == "acos":
                result = _math.degrees(_math.acos(angle))
            elif fn == "atan":
                result = _math.degrees(_math.atan(angle))
            return f"{fn}({_fmt(angle)}°) = {_fmt(result)}"

    # ── 10. Statistics ──────────────────────────────────────────────────────
    stat_match = re.search(
        r'\b(mean|average|median|mode|standard\s+deviation|std\s+dev|variance|sum|range)\s+(?:of\s+)?((?:[\d.]+(?:\s*,\s*|\s+and\s+|\s+)){1,}[\d.]+)',
        text
    )
    if stat_match:
        import statistics as _stats
        op = stat_match.group(1).lower().replace(" ", "_")
        nums_str = re.findall(r'[\d.]+', stat_match.group(2))
        nums = [float(x) for x in nums_str]
        if nums:
            label = ", ".join(_fmt(n) for n in nums)
            if "mean" in op or "average" in op:
                return f"Mean of [{label}] = {_fmt(_stats.mean(nums))}"
            elif "median" in op:
                return f"Median of [{label}] = {_fmt(_stats.median(nums))}"
            elif "mode" in op:
                return f"Mode of [{label}] = {_fmt(_stats.mode(nums))}"
            elif "standard" in op or "std" in op:
                return f"Std Dev of [{label}] = {_fmt(_stats.stdev(nums))}" if len(nums) > 1 else "Need at least 2 values."
            elif "variance" in op:
                return f"Variance of [{label}] = {_fmt(_stats.variance(nums))}" if len(nums) > 1 else "Need at least 2 values."
            elif "sum" in op:
                return f"Sum of [{label}] = {_fmt(sum(nums))}"
            elif "range" in op:
                return f"Range of [{label}] = {_fmt(max(nums) - min(nums))}"

    # ── 11. Geometry ────────────────────────────────────────────────────────
    # Area of circle
    m = re.search(r'area\s+of\s+(?:a\s+)?circle\s+(?:with\s+)?(?:radius|r)\s*([\d.]+)', text)
    if m:
        r = float(m.group(1))
        area = _math.pi * r * r
        return f"Area of circle (radius={_fmt(r)}) = pi x {_fmt(r)}^2 = {_fmt(area)}"

    # Circumference of circle
    m = re.search(r'(?:circumference|perimeter)\s+of\s+(?:a\s+)?circle\s+(?:with\s+)?(?:radius|r)\s*([\d.]+)', text)
    if m:
        r = float(m.group(1))
        circ = 2 * _math.pi * r
        return f"Circumference of circle (radius={_fmt(r)}) = 2 x pi x {_fmt(r)} = {_fmt(circ)}"

    # Area of rectangle
    m = re.search(r'area\s+of\s+(?:a\s+)?rectangle\s+(?:with\s+)?(?:length|l)?\s*([\d.]+)\s+(?:and\s+)?(?:width|w|breadth)?\s*([\d.]+)', text)
    if m:
        l, w = float(m.group(1)), float(m.group(2))
        return f"Area of rectangle ({_fmt(l)} x {_fmt(w)}) = {_fmt(l * w)}"

    # Area of triangle
    m = re.search(r'area\s+of\s+(?:a\s+)?triangle\s+(?:with\s+)?(?:base|b)?\s*([\d.]+)\s+(?:and\s+)?(?:height|h)?\s*([\d.]+)', text)
    if m:
        b, h = float(m.group(1)), float(m.group(2))
        return f"Area of triangle (base={_fmt(b)}, height={_fmt(h)}) = {_fmt(0.5 * b * h)}"

    # Volume of sphere
    m = re.search(r'volume\s+of\s+(?:a\s+)?sphere\s+(?:with\s+)?(?:radius|r)\s*([\d.]+)', text)
    if m:
        r = float(m.group(1))
        vol = (4 / 3) * _math.pi * r ** 3
        return f"Volume of sphere (radius={_fmt(r)}) = (4/3) x pi x {_fmt(r)}^3 = {_fmt(vol)}"

    # ── 12. Financial ───────────────────────────────────────────────────────
    # Simple interest: P, R, T
    m = re.search(
        r'simple\s+interest\s+(?:on\s+)?([\d.]+)\s+at\s+([\d.]+)\s*(?:percent|%)\s+for\s+([\d.]+)\s*(?:year|yr)',
        text
    )
    if m:
        p, r, t = float(m.group(1)), float(m.group(2)), float(m.group(3))
        si = (p * r * t) / 100
        return f"Simple Interest: P={_fmt(p)}, R={_fmt(r)}%, T={_fmt(t)} yr. SI = {_fmt(si)}, Total = {_fmt(p + si)}"

    # Compound interest
    m = re.search(
        r'compound\s+interest\s+(?:on\s+)?([\d.]+)\s+at\s+([\d.]+)\s*(?:percent|%)\s+for\s+([\d.]+)\s*(?:year|yr)',
        text
    )
    if m:
        p, r, t = float(m.group(1)), float(m.group(2)), float(m.group(3))
        amount = p * (1 + r / 100) ** t
        ci = amount - p
        return f"Compound Interest: P={_fmt(p)}, R={_fmt(r)}%, T={_fmt(t)} yr. CI = {_fmt(ci)}, Amount = {_fmt(amount)}"

    # ── 13. Symbolic Equation Solving (via sympy) ───────────────────────────
    # Use `text` (filler-stripped) as the equation source so "solve x^2 - 5x + 6 = 0" works
    eq_source = text if "=" in text else (raw if "=" in raw else None)
    if eq_source:
        try:
            import sympy as _sp
            # Supports: "x^2 - 5x + 6 = 0", "2x + 3 = 7", "x^3 = 27"
            x = _sp.Symbol('x')
            eq_str = eq_source.strip()
            # Replace ^ with ** for sympy
            eq_str = re.sub(r'\^', '**', eq_str)
            # Replace implicit multiplication: "5x" -> "5*x"
            eq_str = re.sub(r'(\d)([a-zA-Z])', r'\1*\2', eq_str)
            lhs_str, rhs_str = eq_str.split("=", 1)
            lhs = _sp.sympify(lhs_str.strip(), locals={"x": x, "e": _sp.E, "pi": _sp.pi})
            rhs = _sp.sympify(rhs_str.strip(), locals={"x": x, "e": _sp.E, "pi": _sp.pi})
            equation = _sp.Eq(lhs, rhs)
            solutions = _sp.solve(equation, x)
            if solutions:
                # Filter to real solutions for natural language output
                real_sols = [s for s in solutions if _sp.im(s) == 0]
                sol_list = real_sols if real_sols else solutions
                sol_str = ", ".join(str(_sp.nsimplify(s, rational=False)) for s in sol_list)
                return f"Solution: x = {sol_str}"
            else:
                return "No real solutions found."
        except Exception as sym_err:
            logger.debug(f"[MATH] sympy solve failed: {sym_err}")


    # ── 14. Free-form expression evaluation ─────────────────────────────────
    # Normalize the text for eval
    expr = text
    # Word → operator substitutions
    word_ops = [
        (r'\btimes\b', '*'),
        (r'\bmultiplied\s+by\b', '*'),
        (r'\bdivided\s+by\b', '/'),
        (r'\bplus\b', '+'),
        (r'\bminus\b', '-'),
        (r'\bover\b', '/'),
        (r'\bto\s+the\s+power\s+of\b', '**'),
        (r'\bto\s+the\s+power\b', '**'),
        (r'\^', '**'),
        (r'\bmod\b', '%'),
        (r'\bmodulo\b', '%'),
    ]
    for pattern, repl in word_ops:
        expr = re.sub(pattern, repl, expr, flags=re.IGNORECASE)

    # Normalize whitespace
    expr = re.sub(r'\s+', '', expr)

    # Try safe eval
    try:
        result = _safe_eval(expr)
        if result is not None:
            try:
                result_f = float(result)
            except (TypeError, ValueError):
                result_f = None
            if result_f is not None:
                if result_f == int(result_f):
                    return f"The answer is {int(result_f)}."
                else:
                    return f"The answer is {result_f:.10g}."
    except ZeroDivisionError:
        return "Cannot divide by zero."
    except OverflowError:
        return "Result is too large to compute."

    # ── 15. Sympy general expression fallback ───────────────────────────────
    try:
        import sympy as _sp
        sym_expr = raw
        sym_expr = re.sub(r'\^', '**', sym_expr)
        sym_expr = re.sub(r'(\d)([a-zA-Z])', r'\1*\2', sym_expr)
        evaluated = _sp.sympify(sym_expr, locals={"pi": _sp.pi, "e": _sp.E})
        numeric = float(evaluated.evalf())
        return f"The answer is {_fmt(numeric)}."
    except Exception:
        pass

    return None

def translate_text(text: str) -> Optional[str]:
    """Translate text to another language"""
    try:
        # Extract source and target languages
        text_lower = text.lower()
        
        # Pattern: "translate [text] to [language]" or "say [text] in [language]"
        patterns = [
            r'translate\s+["\']?(.+?)["\']?\s+(?:to|into)\s+(\w+)',
            r'say\s+["\']?(.+?)["\']?\s+in\s+(\w+)',
        ]
        
        target_text = None
        target_lang = None
        
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                target_text = match.group(1).strip()
                target_lang = match.group(2).strip()
                break
        
        if not target_text or not target_lang:
            return None
        
        try:
            from deep_translator import GoogleTranslator
            
            # Map language names to language codes
            lang_map = {
                "spanish": "es",
                "french": "fr",
                "german": "de",
                "italian": "it",
                "portuguese": "pt",
                "russian": "ru",
                "chinese": "zh-CN",
                "japanese": "ja",
                "korean": "ko",
                "hindi": "hi",
                "telugu": "te",
                "tamil": "ta",
                "kannada": "kn",
                "malayalam": "ml",
            }
            
            lang_code = lang_map.get(target_lang.lower(), target_lang.lower())
            
            translator = GoogleTranslator(source='en', target=lang_code)
            translated = translator.translate(target_text)
            
            return f"{target_text} in {target_lang} is: {translated}"
            
        except ImportError:
            return f"Translation service not available. Please install deep_translator."
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return f"Could not translate text: {str(e)}"
            
    except Exception as e:
        logger.error(f"Error in translate_text: {e}")
        return None

def shutdown_system(user_id: int = 1, confirmed: bool = False) -> Optional[str]:
    """Shutdown the system via UniversalOSGateway security boundary."""
    try:
        from core.os_gateway import get_os_gateway
        from core.os_gateway.operation_model import OSOperation, OSCapability, OSOperationType, OSRiskLevel
        op = OSOperation(
            capability=OSCapability.SYSTEM_POWER,
            operation_type=OSOperationType.SHUTDOWN,
            target="system",
            risk_level=OSRiskLevel.SYSTEM_CRITICAL,
            requires_confirmation=True,
            original_goal="shutdown system",
        )
        res = get_os_gateway().execute(op, user_id=user_id, confirmed_by_user=confirmed)
        return res.message
    except Exception as e:
        logger.error(f"[SAFETY] Error during shutdown gateway execution: {e}")
        return f"Failed to initiate shutdown safely: {str(e)}"

def restart_system(user_id: int = 1, confirmed: bool = False) -> Optional[str]:
    """Restart the system via UniversalOSGateway security boundary."""
    try:
        from core.os_gateway import get_os_gateway
        from core.os_gateway.operation_model import OSOperation, OSCapability, OSOperationType, OSRiskLevel
        op = OSOperation(
            capability=OSCapability.SYSTEM_POWER,
            operation_type=OSOperationType.RESTART,
            target="system",
            risk_level=OSRiskLevel.SYSTEM_CRITICAL,
            requires_confirmation=True,
            original_goal="restart system",
        )
        res = get_os_gateway().execute(op, user_id=user_id, confirmed_by_user=confirmed)
        return res.message
    except Exception as e:
        logger.error(f"[SAFETY] Error during restart gateway execution: {e}")
        return f"Failed to initiate restart safely: {str(e)}"

def lock_system(user_id: int = 1, confirmed: bool = False) -> Optional[str]:
    """Lock the system via UniversalOSGateway security boundary."""
    try:
        from core.os_gateway import get_os_gateway
        from core.os_gateway.operation_model import OSOperation, OSCapability, OSOperationType, OSRiskLevel
        op = OSOperation(
            capability=OSCapability.SYSTEM_POWER,
            operation_type=OSOperationType.LOCK,
            target="system",
            risk_level=OSRiskLevel.MODIFYING,
            requires_confirmation=False,
            original_goal="lock system",
        )
        res = get_os_gateway().execute(op, user_id=user_id, confirmed_by_user=True)
        return res.message
    except Exception as e:
        logger.error(f"[SAFETY] Error during lock gateway execution: {e}")
        return f"Failed to lock system safely: {str(e)}"

def sleep_system(user_id: int = 1, confirmed: bool = False) -> Optional[str]:
    """Put the system to sleep via UniversalOSGateway security boundary."""
    try:
        from core.os_gateway import get_os_gateway
        from core.os_gateway.operation_model import OSOperation, OSCapability, OSOperationType, OSRiskLevel
        op = OSOperation(
            capability=OSCapability.SYSTEM_POWER,
            operation_type=OSOperationType.SLEEP,
            target="system",
            risk_level=OSRiskLevel.SYSTEM_CRITICAL,
            requires_confirmation=True,
            original_goal="sleep system",
        )
        res = get_os_gateway().execute(op, user_id=user_id, confirmed_by_user=confirmed)
        return res.message
    except Exception as e:
        logger.error(f"[SAFETY] Error during sleep gateway execution: {e}")
        return f"Failed to sleep system safely: {str(e)}"

def get_weather(query: str) -> Optional[str]:
    """Get weather information (placeholder - needs API integration)"""
    try:
        from extensions.weather_engine import get_weather_for_query
        return get_weather_for_query(query)
    except ImportError:
        return "Weather service not available."
    except Exception as e:
        logger.error(f"Error getting weather: {e}")
        return f"Could not retrieve weather information: {str(e)}"

def generate_random_numbers(query: str) -> str:
    """
    Generate random numbers locally based on natural language command.
    Handles counts and ranges such as:
    - 'tell me some random numbers from 1 to 10'
    - 'give me 5 random numbers from 1 to 100'
    - 'generate 10 random numbers'
    - 'tell me 5 random numbers between 1 and 500'
    """
    try:
        import random
        text = query.lower().strip()

        # Extract range: "from X to Y" or "between X and Y"
        min_val = 1
        max_val = 100
        m_range = re.search(r'\b(?:from|between)\s+(\d+)\s+(?:to|and)\s+(\d+)\b', text)
        if m_range:
            min_val = int(m_range.group(1))
            max_val = int(m_range.group(2))
            if min_val > max_val:
                min_val, max_val = max_val, min_val
        elif "1 to 10" in text or "1 and 10" in text:
            min_val, max_val = 1, 10
        elif "1 to 100" in text or "1 and 100" in text:
            min_val, max_val = 1, 100
        elif "1 to 500" in text or "1 and 500" in text:
            min_val, max_val = 1, 500

        # Extract count
        count = 5
        m_count = re.search(r'\b(?:give\s+me|generate|tell\s+me|pick|show\s+me)?\s*(\d+)\s+random\s+numbers?\b', text)
        if m_count:
            count = int(m_count.group(1))
        elif any(k in text for k in ["a random number", "one random number", "single random number"]):
            count = 1
        elif "some random numbers" in text:
            count = 5

        count = max(1, min(100, count))

        # Generate numbers
        range_size = max_val - min_val + 1
        if count <= range_size:
            numbers = random.sample(range(min_val, max_val + 1), count)
        else:
            numbers = [random.randint(min_val, max_val) for _ in range(count)]

        nums_str = ", ".join(str(n) for n in numbers)
        if count == 1:
            return f"Your random number between {min_val} and {max_val} is {numbers[0]}."
        return f"Here are {count} random numbers between {min_val} and {max_val}: {nums_str}."
    except Exception as e:
        logger.error(f"Error generating random numbers: {e}")
        return "I was unable to generate random numbers."

# Export functions
__all__ = [
    'tell_time',
    'tell_date',
    'solve_math',
    'generate_random_numbers',
    'translate_text',
    'shutdown_system',
    'restart_system',
    'lock_system',
    'sleep_system',
    'get_weather',
]
