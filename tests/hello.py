#!/usr/bin/env python3
"""A silly 100-line script that generates ASCII art patterns."""

import math
import random
import time


def sine_wave(width=60, amplitude=10, frequency=0.15, phase=0.0):
    """Generate a sine wave pattern."""
    lines = []
    for y in range(amplitude * 2 + 1):
        row = []
        for x in range(width):
            wave_y = amplitude + int(amplitude * math.sin(frequency * x + phase))
            if y == wave_y:
                row.append("●")
            elif y == amplitude:
                row.append("·")
            else:
                row.append(" ")
        lines.append("".join(row))
    return "\n".join(lines)


def diamond(size=10):
    """Generate a diamond pattern."""
    lines = []
    for i in range(size):
        spaces = size - i - 1
        stars = 2 * i + 1
        lines.append(" " * spaces + "◆" * stars)
    for i in range(size - 2, -1, -1):
        spaces = size - i - 1
        stars = 2 * i + 1
        lines.append(" " * spaces + "◆" * stars)
    return "\n".join(lines)


def spiral(size=15):
    """Generate a spiral of dots."""
    lines = []
    for y in range(size):
        row = []
        for x in range(size):
            cx, cy = size / 2, size / 2
            dx, dy = x - cx, y - cy
            dist = math.sqrt(dx * dx + dy * dy)
            angle = math.atan2(dy, dx)
            spiral_r = dist - angle / (2 * math.pi)
            if abs(spiral_r - round(spiral_r)) < 0.15:
                row.append("○")
            else:
                row.append("  ")
        lines.append("".join(row))
    return "\n".join(lines)


def checkerboard(rows=8, cols=16):
    """Generate a checkerboard pattern."""
    lines = []
    for r in range(rows):
        row = []
        for c in range(cols):
            row.append("██" if (r + c) % 2 == 0 else "  ")
        lines.append("".join(row))
    return "\n".join(lines)


def random_sparkle(width=40, height=10, density=0.08):
    """Generate a random sparkle field."""
    lines = []
    symbols = ["·", "✦", "✧", "⋆", "★", "☆", "⁕"]
    for _ in range(height):
        row = []
        for _ in range(width):
            if random.random() < density:
                row.append(random.choice(symbols))
            else:
                row.append(" ")
        lines.append("".join(row))
    return "\n".join(lines)


def tree(height=12):
    """Generate a Christmas tree."""
    lines = []
    for i in range(height):
        spaces = height - i - 1
        leaves = 2 * i + 1
        row = " " * spaces
        for j in range(leaves):
            if random.random() < 0.1:
                row += "○"
            else:
                row += "▲"
        lines.append(row)
    trunk_width = max(3, height // 3)
    trunk_spaces = height - trunk_width // 2 - 1
    lines.append(" " * trunk_spaces + "█" * trunk_width)
    lines.append(" " * trunk_spaces + "█" * trunk_width)
    return "\n".join(lines)


def main():
    print("=" * 60)
    print("  ASCII Art Generator")
    print("=" * 60)
    time.sleep(0.2)
    print()

    generators = [
        ("Sine Wave", lambda: sine_wave(phase=time.time())),
        ("Diamond", lambda: diamond(8)),
        ("Spiral", lambda: spiral(14)),
        ("Checkerboard", checkerboard),
        ("Sparkle Field", random_sparkle),
        ("Christmas Tree", lambda: tree(10)),
    ]

    for i, (name, gen) in enumerate(generators, 1):
        print(f"--- {i}. {name} ---")
        result = gen()
        print(result)
        print()
        time.sleep(0.15)

    print("=" * 60)
    print("  Done! Generated {} patterns.".format(len(generators)))
    print("=" * 60)


if __name__ == "__main__":
    main()
