# Portal preview

Run:

```
python scripts/build_demo.py
python -m http.server 8080 --directory frontend
```

Open http://127.0.0.1:8080.

The live portal replaces the previous duplicated static mockup. Existing portfolio images remain available in `frontend/` and are used for repository/social previews; the source of truth for behavior is the interactive page.
