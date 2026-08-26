/**
 * MEGAGRID — Ponte CCEE (PLD semanal)
 * A API da CCEE geobloqueia IPs fora do Brasil (403 "Bloqueio") — os runners
 * do GitHub Actions ficam nos EUA. Esta function roda na Vercel em SÃO PAULO
 * (região gru1, ver vercel.json) e repassa o JSON CKAN para o robô.
 *
 * GET /api/ccee-pld?year=2026  → JSON cru do datastore_search da CCEE
 */

const CCEE_API = 'https://dadosabertos.ccee.org.br/api/3/action';

// Recursos pld_media_semanal por ano (mesmos IDs do fetch_data.py)
const RESOURCES = {
  '2025': 'b1a35c4b-a3ad-4572-9927-4dc5724578bd',
  '2026': 'e34f98e8-68df-4a22-972f-02cb621ec978',
};

const UA = {
  'User-Agent':
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
    '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
  Accept: 'application/json',
  'Accept-Language': 'pt-BR,pt;q=0.9',
};

async function cceeGet(path, params) {
  const qs = new URLSearchParams(params).toString();
  const r = await fetch(`${CCEE_API}/${path}?${qs}`, { headers: UA });
  if (!r.ok) throw new Error(`CCEE HTTP ${r.status}`);
  return r.json();
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  // cache na edge: 1h fresco + 1 dia stale (protege a CCEE e o robô)
  res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=86400');

  const year = String(req.query.year || new Date().getFullYear());

  try {
    let resourceId = RESOURCES[year];

    // descoberta dinâmica p/ anos futuros (auto-heal)
    if (!resourceId) {
      const pkg = await cceeGet('package_show', { id: 'pld_media_semanal' });
      const hit = (pkg.result?.resources || []).find((x) =>
        (x.name || '').includes(year)
      );
      resourceId = hit?.id;
      if (!resourceId) throw new Error(`recurso ${year} não encontrado`);
    }

    const data = await cceeGet('datastore_search', {
      resource_id: resourceId,
      limit: '300',
      sort: '_id asc',
    });
    return res.status(200).json(data);
  } catch (err) {
    console.error('[ccee-pld]', err.message);
    return res.status(502).json({ error: err.message });
  }
}
