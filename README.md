# Calendari del Barça 2026/2027

Calendari públic per subscripció del primer equip masculí de futbol del FC Barcelona. El feed
`public/barca.ics` conté únicament LaLiga, UEFA Champions League i Copa del Rei. No inclou
amistosos, Supercopa d'Espanya, Trofeu Joan Gamper, Mundial de Clubs, seleccions, Barça Atlètic,
juvenil, femení, Copa Catalunya ni cap altra competició.

## Arquitectura

- Python 3.12, `requests` i fitxers JSON; no hi ha base de dades ni frontend framework.
- `src/providers/` adapta cada font a un model comú `Game`.
- `src/calendar/` genera un ICS amb timezone `Europe/Madrid`.
- `data/provider-cache/` conserva l'últim conjunt de partits vàlid per provider.
- `data/standings/laliga/` i `data/standings/champions/` guarden snapshots per jornada.
- `data/sync-state.json` aplica un gate de 24 hores entre syncs correctes.
- `public/` és una landing estàtica i el feed publicable a GitHub Pages.

La temporada se configura con `BARCA_SEASON_START_YEAR` (por defecto `2026`). Los providers
derivan `2026/2027` desde esa variable. El endpoint de UEFA usa una convención distinta y recibe
el año final de temporada (`2027`). La duración por defecto de un partido de fútbol es 135 minutos
(2 h 15 min), configurable con `BARCA_MATCH_DURATION_MINUTES`.

## Fonts reals i contractes validats

### LaLiga

Font operativa: API pública oficial de LaLiga, consumida por su frontend:

- `GET https://apim.laliga.com/public-service/api/v1/matches`
- Paràmetres: `subscriptionSlug=laliga-easports-{any inicial}`, `seasonYear={any inicial}`,
  `teamSlug=fc-barcelona`, `limit`, `offset`, `orderField=date`, `orderType=asc`.
- El provider també consulta el mateix endpoint sense `teamSlug` per conèixer l'estat de totes les
  jornades i no assumir cap nombre fix de partits.
- El provider valida l'edició amb el slug de subscripció, descobreix Barça per `teamSlug` i descobreix
  cada partit a partir de `matches`; no hardcodea 38, dates, rivals ni horaris.
- Classificació: `GET https://apim.laliga.com/public-service/api/v1/subscriptions/{slug}/standing`
  i `?week={jornada}` per a una jornada concreta. Retorna la taula completa amb posició, equip,
  PJ, punts i estadístiques de gols.
- La pàgina oficial de calendari també publica el JSON `https://assets.laliga.com/assets/calendar/`;
  serveix per corroborar la temporada i les jornades, però no és la font principal perquè no conté
  de manera suficientment rica hora, estat, estadi i resultat.
- El frontend exposa una clau de subscripció pública. El projecte usa el valor públic actual per
  defecte i permet substituir-lo amb `LALIGA_API_KEY`.

### UEFA Champions League

Font operativa: APIs públiques oficials consumides per UEFA.com:

- `GET https://match.uefa.com/v5/matches`
- Paràmetres: `competitionId=1`, `seasonYear={any final}`, `order=ASC`, `offset`, `limit`.
  La resposta es pagina fins que no queden registres; després es filtra `competitionPhase=TOURNAMENT`
  i la competició `UCL` masculina. `phase=TOURNAMENT` no es dóna per assumit perquè la resposta
  observada no el va aplicar de manera consistent.
- Barça es descobreix pels objectes `homeTeam`/`awayTeam` de la resposta, no amb una llista fixa
  d'adversaris. Cada partit usa l'`id` de UEFA, `round`, `matchday`, `kickOffTime`, `stadium`,
  `status` i el marcador quan existeix.
- UEFA identifica la temporada amb l'any final: per 2026/27 el provider consulta `seasonYear=2027`.
  Això és diferent de LaLiga i està encapsulat al provider.
- Classificació: `GET https://standings.uefa.com/v1/standings?competitionId=1&seasonYear=2027`.
  Es publica només quan el `round.metaData.type` és `GROUP_STANDINGS` (fase lliga). En fases
  eliminatòries no s'afegeix cap taula.
- La resposta de standings oficial validada no exposa un paràmetre històric documentat per jornada.
  Per això el sistema congela la taula oficial observada quan una jornada queda completada. Si un
  sync es perd tota la finestra entre dues jornades, aquesta limitació de la font impedeix reconstruir
  retrospectivament i amb garanties tots els criteris de desempat UEFA.
- La clau pública que UEFA exposa al frontend es pot substituir amb `UEFA_API_KEY`.

### Copa del Rei

- La RFEF és la referència oficial de la competició i del calendari: 
  `https://rfef.es/es/competiciones/copa-del-rey`.
- El portal de resultats enllaçat per la RFEF demana una sessió i no és una font automàtica pública
  estable. Per a les dades operatives s'utilitza l'API pública de LaLiga, que publica la mateixa
  competició i és comprovable sense serveis de pagament:
  `GET https://apim.laliga.com/public-service/api/v1/subscriptions?competitionSlug=copa-del-rey`.
- El provider selecciona la subscripció amb `year={any inicial}` de manera dinàmica i després usa
  `GET .../api/v1/matches` amb `subscriptionSlug`, `seasonYear`, `teamSlug=fc-barcelona`, paginació
  i ordenació per data. Descobreix la ronda des de `gameweek.name` i no fixa cap nombre de partits.
- En el sync del 29/08/2026 encara no existia una subscripció pública `2026/2027` en aquest endpoint.
  El provider ho tracta com a absència esperada i no com a error; quan es publiqui, entrarà sense
  canviar el codi. No es guarden snapshots de Copa.
- Estat d'auditoria: `Copa discovery pending official 2026/27 publication`.
- Fallback recomanat: mantenir RFEF com a font de referència i afegir-ne un adaptador només quan
  publiqui un endpoint/frontend públic estable i usable; no fer scraping de les pàgines protegides
  ni introduir una font comercial mentre no sigui necessari.

## UIDs, estados y fail-closed

La identitat és `competition + season + source_game_id`. El fallback és `competition + season +
fase/ronda + local + visitant`, amb normalització Unicode mínima. La UID no incorpora data, hora,
estadi, estat ni marcador, de manera que una reprogramació actualitza el mateix `VEVENT`.

Es normalitzen `scheduled`, `live`, `completed`, `postponed` i `cancelled`. Un error HTTP, JSON
invàlid, payload incomplet o buidatge inesperat atura el sync abans d'escriure el feed. Els partits
desapareguts temporalment es recuperen de `data/provider-cache/`; en absència de subscripció de Copa
encara no publicada, es permet 0 inicial però mai esborra una cache anterior vàlida.

## Classificacions i snapshots

Per a LaLiga, una jornada completada usa el snapshot `data/standings/laliga/{season}/round-XX.json`
si existeix; si no, consulta `standing?week=XX` i el desa només si no existia. Una jornada en curs i
els partits futurs usen la classificació actual més recent; si no n'hi ha, mostren
`Classificació encara no disponible`.

Per a Champions, la mateixa política usa `matchday-XX.json`, però només durant la fase lliga.
Quan el partit és de playoff o eliminatòria, l'ICS mostra la fase (i `Anada`/`Tornada` quan la font
ho dona) sense una classificació enganyosa. Els fitxers JSON tenen ordre de claus estable i es poden
inspeccionar directament.

## Execució local

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python scripts/sync_calendar.py --force
```

Per validar sense escriure:

```bash
python scripts/sync_calendar.py --force --dry-run
```

Variables suportades:

- `BARCA_SEASON_START_YEAR` — any inicial, per defecte `2026`.
- `BARCA_MATCH_DURATION_MINUTES` — per defecte `135`.
- `LALIGA_API_KEY` — override de la clau pública exposada pel frontend oficial.
- `LALIGA_SUBSCRIPTION_SLUG` — override només si LaLiga canvia el patró de slug.
- `UEFA_API_KEY` — override de la clau pública exposada pel frontend oficial.

La landing es pot servir amb `python -m http.server --directory public 8000`. El fitxer
`public/app.js` calcula el feed a partir de la URL actual, o permet establir una única constant
`PUBLIC_FEED_URL_OVERRIDE` després de crear el repositori. No hi ha cap URL GitHub inventada repetida
en el projecte. Apple Calendar rep l'equivalent `webcal://`; Google rep una guia manual
per afegir el feed des d'un ordinador, sense Google Calendar API, OAuth ni Service Account.

## GitHub Pages i Actions

1. Crear més endavant un repositori buit i configurar Pages amb GitHub Actions.
2. Pujar aquest directori sense fer `git init` automàticament en aquesta fase.
3. Opcionalment definir `LALIGA_API_KEY` i `UEFA_API_KEY` com a repository variables; les claus són
   credencials públiques del frontend, no secrets privats.
4. Revisar la URL final i, si es vol, configurar `PUBLIC_FEED_URL_OVERRIDE` a `public/app.js`.
5. El workflow programat/manual fa checkout, sync, actualitza dades generades, fa commit automàtic
   només de dades i desplega Pages. El cron diari respecta el gate de ~24 hores; `workflow_dispatch`
   amb `force: true` el salta.
6. Un push de frontend només fa checkout, upload de `public/` i deploy; no executa providers.

El trigger de frontend inclou `index.html`, `styles.css`, `app.js`, `favicon.svg` i `public/assets/**`,
però no `public/barca.ics`, evitant bucles causats pels commits automàtics del sync.

El feed es comprova/sincronitza aproximadament cada 24 hores. Google Calendar i Apple Calendar
decideixen el seu propi interval de consulta del feed; la propagació d'un canvi no és instantània ni
controlable per aquest projecte. La promesa és la sincronització del feed, no un refresco exacte
del client de l'usuari. La subscripció és persistent, però un client pot trigar hores (o més, segons
cache i configuració) a mostrar un canvi.
