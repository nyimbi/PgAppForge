# Tutorial 08: Generating a Mobile App

`flask forge gen mobile` generates a production-ready React Native app using Expo SDK 52 from your PostgreSQL schema. The app includes list/detail/form screens for every table, offline sync via WatermelonDB, biometric authentication, and per-column-type field components for JSONB, HSTORE, INET, arrays, and date ranges.

## Prerequisites

- pgappforge installed: `pip install pgappforge`
- Node.js 20+ and npm
- Expo CLI: `npm install -g expo-cli`
- A PostgreSQL database (this tutorial uses the `employees` example)

## Step 1 — Generate the Mobile App

```bash
flask forge gen mobile \
  --uri postgresql://localhost/employees \
  --output-dir ./empapp_mobile/ \
  --name EmployeeApp \
  --api-url https://api.example.com
```

The generator introspects the database, then writes the React Native project:

```
Introspecting postgresql://localhost/employees ...
  Found 8 tables, 63 columns, 12 foreign keys
Generating React Native (Expo SDK 52) → ./empapp_mobile/
  ✓ package.json          (pinned Expo SDK 52 dependencies)
  ✓ app.json              (Expo config, bundle ID, splash screen)
  ✓ app/(tabs)/index.tsx  (home screen with table list)
  ✓ app/employee/         (list, detail, form screens)
  ✓ app/department/
  ✓ app/salaries/
  ✓ app/titles/
  ✓ components/fields/    (26 field components — text, jsonb, date, ...)
  ✓ lib/api.ts            (TanStack Query hooks for every endpoint)
  ✓ lib/schema.ts         (Zod validation schemas)
  ✓ lib/sync.ts           (WatermelonDB offline sync)
  ✓ lib/auth.ts           (JWT + biometric authentication)
  ✓ watermelon/           (WatermelonDB model definitions)
Generation complete!
  cd empapp_mobile && npm install && npx expo start
```

To generate web + mobile in a single command:

```bash
flask forge gen all \
  --uri postgresql://localhost/employees \
  --name EmployeeApp \
  --output-dir ./empapp/ \
  --platform all \
  --api-url https://api.example.com \
  --app-id com.example.employeeapp
```

## Step 2 — What Was Generated

```
empapp_mobile/
├── app/                        # expo-router v4 file-system routing
│   ├── (tabs)/
│   │   └── index.tsx           # home screen (table navigator)
│   ├── employee/
│   │   ├── index.tsx           # list screen (FlashList + TanStack Query)
│   │   ├── [id].tsx            # detail screen
│   │   └── new.tsx             # create form (React Hook Form + Zod)
│   ├── department/
│   │   ├── index.tsx
│   │   ├── [id].tsx
│   │   └── new.tsx
│   └── _layout.tsx             # root layout with auth guard
├── components/
│   └── fields/                 # per-type field components
│       ├── TextField.tsx
│       ├── DateField.tsx
│       ├── JsonbField.tsx      # JSON editor with syntax highlighting
│       ├── InetField.tsx       # IP address input with validation
│       ├── ArrayField.tsx      # tag-input for PG array columns
│       └── ...                 # 26 types total
├── lib/
│   ├── api.ts                  # TanStack Query v5 hooks
│   ├── schema.ts               # Zod schemas (one per table)
│   ├── sync.ts                 # WatermelonDB pull/push sync
│   └── auth.ts                 # JWT refresh + expo-local-authentication
├── watermelon/
│   ├── schema.ts               # WatermelonDB table schema
│   └── models/                 # WatermelonDB model classes
├── package.json
├── app.json
└── tsconfig.json
```

**expo-router v4** provides file-system routing — no manual navigation wiring. Each table gets its own directory with `index.tsx` (list), `[id].tsx` (detail), and `new.tsx` (create form).

**TanStack Query v5** handles data fetching, caching, background refetch, and infinite scroll. All API calls go through the pgappforge REST API generated in step 1.

**React Hook Form + Zod** provides type-safe form validation. The Zod schemas are generated from PostgreSQL column types and constraints (NOT NULL → `z.string().min(1)`, `NUMERIC` → `z.number()`, etc.).

**NativeWind v4** applies Tailwind CSS classes to native components for consistent styling across iOS and Android.

## Step 3 — Install and Start

```bash
cd empapp_mobile
npm install

# Start the Expo development server
npx expo start
```

Press `i` to open the iOS Simulator, `a` for an Android emulator, or scan the QR code with the Expo Go app on a physical device.

## Step 4 — Screens and Navigation

**Home screen** — shows all generated tables as navigation cards. Each card displays the table name, row count (fetched from the API), and a "+" button to add a record.

**List screen** (e.g. `/employee/`) — `@shopify/flash-list` renders large datasets at 60 fps. Pull down to refresh. Tap a row to open the detail screen. The search bar filters client-side for the loaded page; a server-side search API call fires after 300ms of no typing.

**Detail screen** (e.g. `/employee/42`) — shows all columns with their display labels. FK columns render as tappable links that navigate to the related record. Long-press anywhere on the screen for the action sheet: Edit, Delete, Share.

**Form screens** — multi-step wizard for tables with more than 8 fields, single-page form for smaller tables. Each field uses the correct input component for its PostgreSQL type. Required fields show a red asterisk. Validation errors appear inline below the field.

**Filter panel** — swipe up from the bottom of any list screen to open a `@gorhom/bottom-sheet` filter panel. Set type, operator, and value for any column. Active filters are shown as chips above the list.

## Step 5 — Offline Sync

The app uses WatermelonDB to store a local SQLite copy of the data. When offline, the app reads from and writes to the local database. When connectivity is restored, the sync layer calls:

```
GET  /api/v1/sync/pull?last_pulled_at=<timestamp>
POST /api/v1/sync/push
```

The pgappforge sync endpoints return only changed records since `last_pulled_at`, minimising data transfer. Conflicts are resolved server-side using last-write-wins by default.

The `lib/sync.ts` file generated by the tool contains a `synchronize()` function you can call manually or hook into `AppState` change events:

```typescript
import { synchronize } from '../lib/sync';
import database from '../watermelon/database';

// Call whenever the app comes to the foreground
await synchronize({ database, apiUrl: API_URL, token: authToken });
```

## Next Steps

- Change the `--api-url` to your production API URL before building for the App Store / Google Play
- Run `npx expo-doctor` in the output directory to verify all dependency versions are Expo SDK 52-compatible
- Enable the BPM workflow plugin before generating to get approval-flow screens in the mobile app automatically
- Generate the desktop wrapper as well: add `--platform all` to produce web + mobile + Electron simultaneously
