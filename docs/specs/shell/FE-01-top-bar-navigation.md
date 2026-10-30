# Spec — FE-01 Top bar and navigation

| | |
|---|---|
| **Story** | [`docs/stories/shell/FE-01-top-bar-navigation.feature`](../../stories/shell/FE-01-top-bar-navigation.feature) |
| **Prototype** | [`docs/prototypes/portal/v3.html`](../../prototypes/portal/v3.html), the top bar of `#landing`, `#home` and `#board` (v3 approved 2026-10-30, with amendments) |
| **Backlog** | Portal shell › Frontend › FE-01 |
| **Depends on** | FE-23 (React app), BE-01 |
| **Spec status** | Approved, 2026-10-30. Sections 2 and 4 to 8 were updated the same day for the approved React proposal |
| **Date** | 2026-10-30 |

## 1. Goal

Every portal screen shows the same top bar as v3: the Odisseia Viagens logo,
the "Serviços" label, the navigation ("Início", "Categorizador") with the
current section highlighted, and the orange rule at the bottom. The user can
move between the landing and the categorizer from any screen.

## 2. Scope

**In scope**

- A `TopBar` component, rendered once by the router layout, so it appears on
  every route that FE-23 creates:
  - Landing: `/`.
  - Categorizer home: `/categorizer`.
  - Categorizer board: `/categorizer/:statementId`.
- The logo files, extracted from the prototype.
- The Montserrat font.

**Out of scope**

- Everything below the top bar. FE-23 leaves temporary placeholders on each
  route, and their own stories replace them: FE-02 (landing), FE-03 to FE-05
  (categorizer home) and FE-06 to FE-13 (board).
- Hover and focus designs beyond section 4.4 (Q4).
- Small screens: FE-20. Loading, error and session-expired states: FE-19.
- The app scaffold, the router, the brand tokens and the test setup: FE-23.
- The server: BE-01.

## 3. Reference measurements

These were measured in Chrome on `v3.html` (`#landing`) with
`getComputedStyle`, not read from the CSS. The template has two layers of
rules: a v2 base and the v3 overrides. Implement these values.

| Element | Property | Value |
|---|---|---|
| Bar | height (border included) | 64px |
| | background | `#FFFFFF` |
| | bottom border | 3px solid orange `#EE5E27` |
| | padding / gap | 0 32px / 24px, flex, `align-items: center` |
| Logo group | layout | flex, gap 8px |
| Logo mark | rendered height | 42px (source image 195×285, decorative, `alt=""`) |
| Logo wordmark | rendered height | 30px (source image 335×115, `alt="Odisseia Viagens"`) |
| "Serviços" | font | Montserrat 500, 13px / 19.5px, muted `#4F5B70` |
| | separator | left border 1.5px solid line `#E2DED8`, padding-left 14px, margin-left 6px |
| Nav | layout | flex, gap 4px, `flex: 1` (pushes the right-hand label to the end) |
| Nav item, inactive | font | Montserrat 500, 14px / 21px, navy `#081B59`, opacity .75 |
| | shape | padding 6px 12px, radius 999px, height 33px |
| Nav item, current | colors | white text on navy `#081B59`, opacity 1 |
| "Equipe financeira" | font | Montserrat 400, 14px, muted `#4F5B70`. **Opacity 1**: v3 draws it at .8, which fails AA, and the change was approved in Q1 |

The v3 screens are 1280px wide. The owner confirmed 1360px as the standard
(`docs/CONSTITUTION.md`, Article 3), and v4 onward uses it. None of the values
above depends on the width, and the top bar spans the full width of the
viewport.

## 4. Behavior

### 4.1 Navigation targets

| Item | Target | Current on |
|---|---|---|
| "Início" | `/` | `/` |
| "Categorizador" | `/categorizer` | `/categorizer` and `/categorizer/:statementId` |

The items are React Router links, so navigation happens in the client, with no
page reload. A direct visit or a reload of any of these paths works because
BE-01 returns `index.html` for them (BE-01, 3.1).

### 4.2 Board → "Categorizador"

The board has its own route, `/categorizer/:statementId`. Selecting
"Categorizador" there navigates to `/categorizer`, which renders the
categorizer home. The board saves every edit through the API (FE-09 and
later), so leaving the board loses no work.

### 4.3 Highlighted item

"Highlighted" means the current item:

- carries `aria-current="page"`;
- is styled from that attribute, not from a separate class, so the visual and
  the accessible state cannot diverge.

The "Categorizador" item is current on `/categorizer` and on every path below
it. `NavLink` marks only an exact match with `aria-current`, so the component
computes the current section from the location itself and sets the attribute.
Exactly one item is current on each route.

### 4.4 Keyboard and focus

- The links are reachable with Tab in visual order: "Início", then
  "Categorizador". The logo is not a link (v3 doesn't make it one).
- Focus uses the browser's default focus ring (Q4). There is no custom hover
  state.

## 5. Implementation

| File (in `app/web/`) | Change |
|---|---|
| `src/components/TopBar/TopBar.tsx` | New. Renders the markup below. Takes no props: the current section comes from `useLocation()` |
| `src/components/TopBar/TopBar.module.css` | New. Uses only the tokens from `src/styles/tokens.css` (FE-23) and the values in section 3 |
| `src/components/TopBar/TopBar.test.tsx` | New. Section 8 |
| `src/assets/odisseia-mark.png`, `src/assets/odisseia-wordmark.png` | New. Decoded from the base64 images in `v3-template.html`, with no re-encoding or resizing. Imported by the component, so Vite hashes them |
| `src/app/Layout.tsx` (FE-23) | Renders `<TopBar />` above the `<Outlet />` |
| `index.html` (FE-23) | Already loads the Montserrat font (Q3) |

Rendered markup:

```html
<header class="topbar">
  <span class="logo">
    <img src="…/odisseia-mark.[hash].png" alt="" height="42">
    <img src="…/odisseia-wordmark.[hash].png" alt="Odisseia Viagens" height="30">
    <span class="svc">Serviços</span>
  </span>
  <nav aria-label="Navegação principal">
    <a href="/" aria-current="page">Início</a>
    <a href="/categorizer">Categorizador</a>
  </nav>
  <span class="who">Equipe financeira</span>
</header>
```

Notes:

- **Copy:** pt-BR, exactly as in v3: "Serviços", "Início", "Categorizador",
  "Equipe financeira". The nav `aria-label` is new; v3 doesn't show it.
- **Class names:** CSS Modules generate the final class names. Tests select
  by role and text, never by class.

## 6. Dependencies

- **v3:** approved on 2026-10-30, with amendments.
- **FE-23:** the React app, router, layout, tokens and Vitest.
- **BE-01:** serves the built app and the fallback, so direct visits and
  reloads work. The pages are served by FastAPI, not by a static server or
  mocked data (owner's decision).

## 7. Verification

QA-03 (pytest-bdd + Playwright) is not set up yet. Until it is, each scenario
is checked by hand in Chrome (Chrome DevTools MCP or a person), with
`make serve` after `make build-web`:

| Scenario / example | Check |
|---|---|
| Top bar shows the brand and navigation | On `/` and `/categorizer`: the wordmark has `alt="Odisseia Viagens"`, "Serviços" follows it, the nav contains exactly "Início" and "Categorizador" in that order, and the bar's computed `border-bottom` is `3px solid rgb(238, 94, 39)` |
| Highlighted — Landing | On `/`: exactly one `[aria-current="page"]`, with the text "Início", and its computed background is `rgb(8, 27, 89)` |
| Highlighted — Categorizer home | On `/categorizer`: exactly one current item, "Categorizador" |
| Highlighted — Categorizer board | On the board of a real statement: exactly one current item, "Categorizador". **Pending validation:** needs the owner's real statement and BE-03 to BE-12 (Q5). No screenshot is kept. The route-level behavior is already covered by the unit tests |
| Navigate Landing → Categorizador | Click "Categorizador" on `/`: the URL is `/categorizer` with no full reload (the network panel shows no new document request) |
| Navigate Categorizer home → Início | Click "Início": the URL is `/` |
| Navigate Categorizer board → Categorizador | On a real statement's board, click "Categorizador": the URL is `/categorizer` and the home renders. **Pending validation**, same as above |
| Direct visit | Reload on `/categorizer`: the top bar renders, and "Categorizador" is current |

Also required for **Done** (`FRONTEND_GUIDELINES.md`, step 7):

- the unit tests in section 8 pass;
- `document.fonts.check('500 14px Montserrat')` is true, so there is no font
  fallback;
- a side-by-side screenshot of the top bar matches v3, with no wrapping or
  clipping, at 1280px (the v3 width) and at 1360px (the standard);
- the console shows no errors, apart from `/api` 404s while those endpoints
  don't exist (BE-01, 3.3).

## 8. Tests

`src/components/TopBar/TopBar.test.tsx` (Vitest + Testing Library). The
component is rendered inside a `MemoryRouter` at a given path. No backend and
no statement data are involved:

| Test | Asserts |
|---|---|
| `renders brand and navigation` | The wordmark has `alt="Odisseia Viagens"`, "Serviços" is shown, the nav has exactly "Início" and "Categorizador" in that order, and "Equipe financeira" is shown |
| `marks exactly one current item` (cases: `/` → Início, `/categorizer` → Categorizador, `/categorizer/abc-123` → Categorizador) | Exactly one link has `aria-current="page"`, and it is the expected one |
| `links point to the section routes` | "Início" → `/`, "Categorizador" → `/categorizer` |
| `navigates without reload` | Clicking "Categorizador" from `/` renders the `/categorizer` route element in the same router |
| `nav has an accessible name` | The `navigation` role has the name "Navegação principal" |
| `logo mark is decorative` | The mark image has `alt=""` and is not in the accessibility tree |

## 9. Open questions

Answers so far (2026-10-30):

- **Q1:** answered "ok". The text stays fixed, and the opacity is removed. v3
  was approved with this amendment (see the version log). The next prototype
  version carries it, and `v3.html` is not edited.
- **Q2 to Q4:** no specific answer. Their recommendations are assumptions.
- **Q5:** the two board checks stay **Pending validation** in the backlog. The
  owner will provide a real statement. They can run only when that statement
  exists **and** BE-03 to BE-12 are Done, because the board needs the upload,
  extraction and board endpoints. The real statement follows the rules in
  `docs/TESTING_GUIDELINES.md` ("Real data in manual validation"). It is
  never committed or turned into a fixture, and no screenshot of it is kept.
- **React:** approved (`docs/proposals/monorepo-and-react.md`), with the
  categorizer migrated one story at a time. Sections 2 and 4 to 8 reflect it.
  Q2's targets lose the trailing slash (`/categorizer`), because the router
  treats both forms the same.

1. **"Equipe financeira":** v3 draws it as fixed text. It could be the team
   name, or a placeholder for the signed-in user from Cloudflare Access
   (BE-23/BE-25), which doesn't exist yet.
   *Recommendation:* render it as fixed text now, and replace it with the user
   identity in a later story once auth exists. Separately, at the measured
   opacity of .8 its contrast is about 4.2:1. That is below the AA level
   (4.5:1) that the constitution requires for small text. Fix it in the
   prototype (remove the opacity, which gives about 6.9:1) rather than
   reproducing it. That is a small design change, so it needs your approval as
   part of the v3 review.
2. **Link targets:** v3 has no `href`s.
   *Recommendation:* `/` and `/categorizer`, as in section 4.1.
3. **Fonts in `app/`:** Article 3 allows Google Fonts in *prototypes*. It says
   nothing about the app. The other option is to self-host the Montserrat
   files under `app/web/src/assets/fonts/`. That avoids a third-party request
   from an internal finance tool, at the cost of about 100 KB of font files in
   the repo.
   *Recommendation:* use the Google Fonts link (the same URL as v3) for now,
   and revisit when OPS-04 puts Cloudflare in front.
4. **Hover and focus:** neither is designed in v3.
   *Recommendation:* the browser's default focus ring and no custom hover for
   now. Design both states in v4, together with the other missing states.
5. **Board scenarios without mocked data:** Two checks need the board on
   screen. The board only appears after a real statement has been uploaded and
   classified (BE-03 to BE-12), and mocked data is ruled out.
   *Recommendation:* FE-01 ships when every other check passes, with these two
   rows marked "pending real statement". FE-01 moves to **Done** once they pass
   on the first real statement, as part of FE-06's verification. Until then,
   the bar's position in the page is enough evidence: it sits outside both
   views, so it can't disappear when the board opens. The alternative is to
   keep FE-01 *In progress* until the statement backend lands.
