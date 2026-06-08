import re


class PolishParser:
    """
    Парсер выражений в обратной польской записи (postfix).
    Операнды — буквенно-цифровые идентификаторы.
    Операторы: +, -, *.
    Стек не ограничен по глубине.
    """

    OPERATORS = {'+', '-', '*'}

    def __init__(self):
        self.stack = []

    def _is_operand(self, token: str) -> bool:
        """Проверяет, является ли токен операндом (буквы и/или цифры)."""
        return bool(re.fullmatch(r'[A-Za-z0-9]+', token))

    # Функции операторов (возвращают строковое представление)
    def _add(self, right: str, left: str) -> str:
        return f"({left}+{right})"

    def _sub(self, right: str, left: str) -> str:
        return f"({left}-{right})"

    def _mul(self, right: str, left: str) -> str:
        return f"({left}*{right})"

    def _apply_operator(self, operator: str):
        """Применяет оператор к двум верхним элементам стека."""
        if len(self.stack) < 2:
            raise Exception(
                f"Недостаточно операндов для '{operator}'. "
                f"Ожидалось 2, в стеке {len(self.stack)}."
            )
        # Без создания явных переменных operand1 / operand2:
        # Левый операнд = предпоследний элемент,
        # правый операнд = последний элемент (извлекается pop'ом).
        if operator == '+':
            self.stack.append(self._add(self.stack.pop(), self.stack.pop()))
        elif operator == '-':
            self.stack.append(self._sub(self.stack.pop(), self.stack.pop()))
        elif operator == '*':
            self.stack.append(self._mul(self.stack.pop(), self.stack.pop()))
        else:
            raise Exception(f"Неизвестный оператор '{operator}'.")

    def parse(self, expression: str) -> str:
        """
        Преобразует строку в обратной польской записи в инфиксную скобочную форму.
        При некорректном выражении вызывает Exception.
        """
        tokens = expression.split()
        self.stack.clear()

        for token in tokens:
            if self._is_operand(token):
                self.stack.append(token)
            elif token in self.OPERATORS:
                self._apply_operator(token)
            else:
                raise Exception(
                    f"Недопустимый токен '{token}'. "
                    f"Разрешены операнды и операторы {self.OPERATORS}."
                )

        if len(self.stack) != 1:
            raise Exception(
                "После обработки в стеке должно остаться ровно одно значение. "
                f"Сейчас: {len(self.stack)}. Проверьте баланс операндов и операторов."
            )

        return self.stack[0]


def remove_redundant_parentheses(expr: str) -> str:
    """
    Убирает из полностью скобочного инфиксного выражения скобки,
    без которых порядок операций не меняется.
    Пример: "(((A+B)-(C+D))*E)" -> "(A+B-(C+D))*E"
    """

    # Приоритеты операторов
    precedence = {'+': 1, '-': 1, '*': 2}

    # ---------- парсинг полностью скобочной записи в AST ----------
    def parse(s: str):
        s = s.strip()
        if not s.startswith('('):
            # это переменная (или число)
            return s

        # Находим парную закрывающую скобку для первой открывающей
        count = 0
        for i, ch in enumerate(s):
            if ch == '(':
                count += 1
            elif ch == ')':
                count -= 1
                if count == 0:
                    closing = i
                    break
        inner = s[1:closing]   # содержимое без внешних скобок

        # Ищем оператор на нулевом уровне вложенности внутри inner
        count = 0
        for i, ch in enumerate(inner):
            if ch == '(':
                count += 1
            elif ch == ')':
                count -= 1
            elif count == 0 and ch in precedence:
                op = ch
                left = inner[:i]
                right = inner[i+1:]
                return (op, parse(left), parse(right))

        # Если оператор не найден – это одиночная переменная в скобках типа "(A)"
        return parse(inner)

    # ---------- форматирование AST с минимальными скобками ----------
    def needs_paren(node_op, parent_op, is_right):
        """True, если подвыражение нужно заключить в скобки."""
        if parent_op is None:
            return False
        p = precedence[node_op]
        pp = precedence[parent_op]
        if p < pp:
            return True
        if p == pp:
            if is_right:
                # Скобки не нужны только когда оба оператора одинаковы и ассоциативны (+ или *)
                return not (node_op == parent_op and node_op in ('+', '*'))
            else:
                return False
        return False

    def format_ast(node, parent_op=None, is_right=False):
        if isinstance(node, str):       # переменная
            return node
        op, left, right = node
        left_str = format_ast(left, parent_op=op, is_right=False)
        right_str = format_ast(right, parent_op=op, is_right=True)

        result = f"{left_str}{op}{right_str}"

        if needs_paren(op, parent_op, is_right):
            return f"({result})"
        return result

    # Запускаем
    ast = parse(expr)
    return format_ast(ast)


# Демонстрация работы
if __name__ == "__main__":
    parser = PolishParser()

    test_expressions = [
        "A B + C D + - E *",  # ((A+B)-(C+D))*E
        "A B + C + D - E - F *",  # (A+B+C-D-E)*F
        "x y +",  # (x+y)
        "a b c +",  # ошибка: лишний операнд
        "x +",  # ошибка: не хватает операндов
    ]

    for expr in test_expressions:
        try:
            infix = parser.parse(expr)
            print(f"'{expr}'  ->  {remove_redundant_parentheses(infix)}")
        except Exception as e:
            print(f"'{expr}'  ->  ОШИБКА: {e}")

