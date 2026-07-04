# VerdaTrace UI Screenshots

The repository stores screenshot samples as SVG text files so the project remains friendly to code review systems that reject binary screenshots.

## Dashboard sample

![VerdaTrace dashboard sample](screenshots/verdatrace-dashboard.svg)

## Pipeline builder sample

![VerdaTrace pipeline builder sample](screenshots/verdatrace-pipeline-builder.svg)

## Run locally and capture real screenshots

```bash
python -m http.server 8080 --directory frontend
gcloud run services describe verdatrace-portal --region europe-west2 --format='value(status.url)'
```
