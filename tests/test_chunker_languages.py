"""Tests for AST chunker across all supported languages."""

from __future__ import annotations

from pathlib import Path

from rrecall.code.chunkers.treesitter import chunk_file


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# --- C# ---

SAMPLE_CSHARP = """\
using System;
using System.Collections.Generic;

namespace MyApp.Models
{
    public class User
    {
        public string Name { get; set; }
        public int Age { get; set; }

        public bool IsAdult()
        {
            return Age >= 18;
        }
    }

    public enum Role
    {
        Admin,
        User,
        Guest
    }
}
"""


def test_csharp_chunks(tmp_path):
    f = _write(tmp_path, "User.cs", SAMPLE_CSHARP)
    chunks = chunk_file(f)
    assert len(chunks) >= 2
    types = {c.chunk_type for c in chunks}
    assert "imports" in types
    names = {c.symbol_name for c in chunks if c.symbol_name}
    assert "User" in names or "Role" in names


def test_csharp_namespace_context(tmp_path):
    f = _write(tmp_path, "User.cs", SAMPLE_CSHARP)
    chunks = chunk_file(f)
    # Classes inside namespace should have parent_symbol set
    class_chunks = [c for c in chunks if c.chunk_type == "class"]
    for c in class_chunks:
        assert c.parent_symbol == "MyApp.Models" or c.parent_symbol


# --- TypeScript ---

SAMPLE_TS = """\
import { Request, Response } from 'express';
import { UserService } from './services';

interface UserDTO {
    id: number;
    name: string;
    email: string;
}

export class UserController {
    constructor(private service: UserService) {}

    async getUser(req: Request, res: Response): Promise<void> {
        const user = await this.service.findById(req.params.id);
        res.json(user);
    }
}

export function createRouter(): void {
    console.log('router created');
}
"""


def test_typescript_chunks(tmp_path):
    f = _write(tmp_path, "controller.ts", SAMPLE_TS)
    chunks = chunk_file(f)
    assert len(chunks) >= 3
    types = {c.chunk_type for c in chunks}
    assert "imports" in types
    names = {c.symbol_name for c in chunks if c.symbol_name}
    assert "UserController" in names or "createRouter" in names


# --- TSX ---

SAMPLE_TSX = """\
import React from 'react';

interface Props {
    name: string;
}

export function Greeting({ name }: Props) {
    return <div>Hello, {name}!</div>;
}
"""


def test_tsx_chunks(tmp_path):
    f = _write(tmp_path, "Greeting.tsx", SAMPLE_TSX)
    chunks = chunk_file(f)
    assert len(chunks) >= 2
    names = {c.symbol_name for c in chunks if c.symbol_name}
    assert "Greeting" in names


# --- HTML ---

SAMPLE_HTML = """\
<!DOCTYPE html>
<html>
<head>
    <title>Test</title>
    <style>
        body { color: red; }
    </style>
</head>
<body>
    <div id="app">
        <h1>Hello</h1>
    </div>
    <script>
        console.log('hi');
    </script>
</body>
</html>
"""


def test_html_chunks(tmp_path):
    f = _write(tmp_path, "index.html", SAMPLE_HTML)
    chunks = chunk_file(f)
    assert len(chunks) >= 1
    # Should have element chunks
    texts = " ".join(c.text for c in chunks)
    assert "Hello" in texts


# --- CSS ---

SAMPLE_CSS = """\
@import url('fonts.css');

body {
    font-family: sans-serif;
    color: #333;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
}

@media (max-width: 768px) {
    .container {
        padding: 0 1rem;
    }
}
"""


def test_css_chunks(tmp_path):
    f = _write(tmp_path, "style.css", SAMPLE_CSS)
    chunks = chunk_file(f)
    assert len(chunks) >= 2
    types = {c.chunk_type for c in chunks}
    # Should have imports and other rule chunks
    assert "imports" in types or "other" in types
    texts = " ".join(c.text for c in chunks)
    assert "container" in texts
