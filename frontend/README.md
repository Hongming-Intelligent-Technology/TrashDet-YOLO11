# TrashDet frontend

React 19 + TypeScript single-page app, built with Vite and served by the Flask backend.

```bash
npm install
npm run dev        # dev server; proxies /api and /static to http://127.0.0.1:5000 (override with VITE_BACKEND_URL)
npm run typecheck  # tsc --noEmit
npm run build      # type-check, then build into ../backend/static/spa (commit the result)
```

## Layout

- `src/main.tsx`: entry point; `src/App.tsx`: layout, navigation and the login guard
- `src/routes.tsx`: routes and their page titles / auth requirements
- `src/views/`: one component per page; `Page.css` next to a page holds its styles,
  scoped under a `scope-*` class on the page's root element
- `src/lib/`: API client, map helpers, patrol-task geometry
- `src/stores/session.ts`: logged-in user (`useSession()` hook)
- `src/hooks/`, `src/components/`: shared hooks and small components
- `src/app.css` and `public/css/`: global styles

Maps use Leaflet and charts use ECharts directly; both are created in `useEffect` and disposed on unmount.
