/**
 * MEGAGRID — Newsletter via Brevo (ex-Sendinblue)
 * Vercel Serverless Function: POST /api/subscribe
 *
 * Variáveis de ambiente (Vercel → Settings → Environment Variables):
 *   BREVO_API_KEY          → API key do Brevo (Settings → SMTP & API → API Keys)   [obrigatória]
 *   BREVO_LIST_ID          → ID da lista de contatos final (inteiro, ex: 3)         [obrigatória]
 *   BREVO_DOI_TEMPLATE_ID  → ID do template de confirmação Double Opt-In (inteiro)  [opcional]
 *
 * Fluxo:
 *   - Se BREVO_DOI_TEMPLATE_ID estiver setado → DOUBLE OPT-IN:
 *       envia e-mail de confirmação; o contato só entra na lista após clicar.
 *       Endpoint: POST /contacts/doubleOptinConfirmation
 *   - Se NÃO estiver setado → fallback: adiciona direto na lista (POST /contacts).
 */

const BREVO_API = 'https://api.brevo.com/v3';
const REDIRECT_URL = 'https://megagrid.com.br/obrigado';

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST, OPTIONS');
    return res.status(405).json({ message: 'Método não permitido' });
  }

  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(204).end();

  // Lê e valida e-mail
  let email;
  try {
    const body = typeof req.body === 'string' ? JSON.parse(req.body) : req.body;
    email = (body && body.email || '').toString().trim().toLowerCase();
  } catch {
    return res.status(400).json({ message: 'Body inválido' });
  }
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return res.status(400).json({ message: 'E-mail inválido' });
  }

  // Variáveis de ambiente
  const apiKey     = process.env.BREVO_API_KEY;
  const listId     = parseInt(process.env.BREVO_LIST_ID || '0', 10);
  const doiTplId   = parseInt(process.env.BREVO_DOI_TEMPLATE_ID || '0', 10);

  if (!apiKey || !listId) {
    console.warn('[subscribe] BREVO_API_KEY ou BREVO_LIST_ID não configurado — simulando sucesso');
    return res.status(200).json({ ok: true, simulated: true });
  }

  const headers = {
    'accept':       'application/json',
    'content-type': 'application/json',
    'api-key':      apiKey,
  };

  try {
    // ----- DOUBLE OPT-IN (confirmação por e-mail) -----
    if (doiTplId) {
      const doiRes = await fetch(`${BREVO_API}/contacts/doubleOptinConfirmation`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          email,
          includeListIds: [listId],
          templateId: doiTplId,
          redirectionUrl: REDIRECT_URL,
          attributes: {
            SOURCE: 'megagrid-site',
            SIGNUP_DATE: new Date().toISOString().split('T')[0],
          },
        }),
      });

      // 201/204 = e-mail de confirmação enviado com sucesso
      if (doiRes.status === 201 || doiRes.status === 204) {
        return res.status(200).json({ ok: true, doi: true });
      }

      const errBody = await doiRes.json().catch(() => ({}));
      console.error('[subscribe] Brevo DOI error:', doiRes.status, errBody);
      // Contato já confirmado anteriormente — tratamos como sucesso
      if (doiRes.status === 400 && /already|duplicate|exist/i.test(JSON.stringify(errBody))) {
        return res.status(200).json({ ok: true, already: true });
      }
      return res.status(500).json({ message: 'Erro ao enviar confirmação. Tente novamente.' });
    }

    // ----- FALLBACK: adiciona direto na lista (sem confirmação) -----
    const brevoRes = await fetch(`${BREVO_API}/contacts`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        email,
        listIds: [listId],
        updateEnabled: true,
        attributes: {
          SOURCE: 'megagrid-site',
          SIGNUP_DATE: new Date().toISOString().split('T')[0],
        },
      }),
    });

    if (brevoRes.status === 201 || brevoRes.status === 204) {
      return res.status(200).json({ ok: true });
    }

    const errBody = await brevoRes.json().catch(() => ({}));
    console.error('[subscribe] Brevo error:', brevoRes.status, errBody);
    if (brevoRes.status === 400 && errBody.code === 'duplicate_parameter') {
      return res.status(200).json({ ok: true });
    }
    return res.status(500).json({ message: 'Erro ao cadastrar. Tente novamente.' });

  } catch (err) {
    console.error('[subscribe] Fetch error:', err);
    return res.status(500).json({ message: 'Erro interno. Tente novamente.' });
  }
}
