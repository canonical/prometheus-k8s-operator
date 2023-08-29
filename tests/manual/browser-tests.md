## Auto redirection
Prometheus automatically redirects from the root to the `/graph` page. This
could fail is the external URL is misconfigured.

Navigate with a browser to the prometheus ingress URL and make sure it
successfully auto redirects to `/graph`.


## Non-empty query results
Prometheus may return empty query results in the browser in the following
situations:

- Ingress path (routing prefix) is set up incorrectly.
- `/metrics` endpoint is wrong.

Navigate with a browser to the prometheus page, and make sure you get non-empty
query results.

If query results are empty, first make sure scrape targets are healthy.
