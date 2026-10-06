"""الوكيل ١ — مرحلة المتصفح: يقرأ ما تعرضه الشاشات فعلاً ويقارنه بالقاعدة. يُستدعى من live_api.py --ui.
المتصفح يُغلق في finally دائماً."""
import re, json, traceback
from decimal import Decimal

import pyotp
from sqlalchemy import text
from app.database import SessionLocal

OUT = 'docs/audit/01_scripts/out'


def q(sql, **kw):
    s = SessionLocal()
    try:
        return s.execute(text(sql), kw).all()
    finally:
        s.close()


def fmt(v, decimals):
    return str(Decimal(str(v)).quantize(Decimal(1).scaleb(-decimals)))


def run(base, username, password, secret, state, results):
    from playwright.sync_api import sync_playwright

    ui = state.setdefault('ui', {})
    mism = ui.setdefault('mismatches', [])
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel='msedge')
        except Exception:
            browser = p.chromium.launch()
        try:
            ctx = browser.new_context(viewport={'width': 1440, 'height': 1500}, locale='ar')
            pg = ctx.new_page()
            reqs = []
            pg.on('request', lambda r: reqs.append((r.method, r.url.replace(base, ''))) if r.method != 'GET' or '/journal' in r.url else None)
            console = []
            bad = []
            pg.on('response', lambda r: bad.append((r.status, r.request.method, r.url.replace(base, '')[:120])) if r.status >= 400 else None)
            pg.on('console', lambda m: console.append((m.type, m.text[:220])) if m.type in ('error', 'warning') else None)
            pg.goto(base + '/', wait_until='networkidle')
            pg.fill('#username', username)
            pg.fill('#password', password)
            pg.click("button:has-text('دخول')")
            pg.wait_for_selector('#totp', timeout=20000)
            pg.fill('#totp', pyotp.TOTP(secret).now())
            pg.click("button:has-text('تأكيد')")
            pg.wait_for_selector('nav.sidebar', timeout=20000)
            ui['sidebar_titles'] = pg.eval_on_selector_all('nav.sidebar button', 'els => els.map(e => e.title || e.innerText)')
            decs = {c: d for c, d in q('select code, decimals from currencies')}
            # ---------- ٠) اختصارات لوحة المفاتيح الموعودة (App.tsx:68-90): هل تُنتج الأثر فعلاً؟
            sc = ui.setdefault('shortcuts', {})
            try:
                pg.locator('body').click(position={'x': 5, 'y': 5})
                pg.keyboard.press('Alt+3'); pg.wait_for_timeout(900)
                sc['Alt+3 → شاشة العملاء'] = pg.locator('.clients-screen').count() > 0
                pg.keyboard.press('Alt+4'); pg.wait_for_timeout(900)
                sc['Alt+4 → مركز السيولة'] = pg.locator('text=مركز السيولة').count() > 0
                pg.keyboard.press('Alt+2'); pg.wait_for_timeout(900)
                sc['Alt+2 → دفتر اليومية'] = pg.locator('.journal-col-center').count() > 0
                pg.keyboard.press('Control+n'); pg.wait_for_timeout(600)
                sc['Ctrl+N → فتح عملية جديدة'] = pg.locator('.new-op-panel').count() > 0
                pg.keyboard.press('Control+n'); pg.wait_for_timeout(600)
                sc['Ctrl+N ثانية → إغلاق'] = pg.locator('.new-op-panel').count() == 0
                pg.locator('body').click(position={'x': 5, 'y': 5})
                pg.keyboard.press('/'); pg.wait_for_timeout(300)
                sc['/ → تركيز البحث'] = pg.evaluate("document.activeElement && document.activeElement.className.includes('app-search')")
                pg.keyboard.press('Escape')
            except Exception:
                sc['error'] = traceback.format_exc()[-300:]


            # ---------- ١) دفتر اليومية: كل قيد اليوم، كل سطر (جانب + مبلغ بخانات العملة)
            try:
                pg.click("button[title^='دفتر اليومية']")
                pg.wait_for_selector('.activity-list', timeout=20000)
                pg.wait_for_timeout(1500)
                n_rows = pg.locator('.activity-row').count()
                ui['journal_rows_shown'] = n_rows
                db_entries = q("""select e.id, e.entry_no, e.status from journal_entries e where e.status='POSTED' order by e.id""")
                ui['journal_posted_in_db'] = len(db_entries)
                checked = 0
                for i in range(n_rows):
                    row = pg.locator('.activity-row').nth(i)
                    row.locator('.activity-item').click()
                    pg.wait_for_timeout(250)
                    head = row.locator('.detail-head').inner_text()
                    entry_no = head.split('·')[0].strip()
                    lines = row.locator("[data-testid=entry-line]")
                    got = []
                    for j in range(lines.count()):
                        ln = lines.nth(j)
                        side = ln.get_attribute('data-side')
                        amt = ln.locator("[data-testid=line-amount]").inner_text().strip()
                        cur = ln.locator('.line-amount .text-muted').inner_text().strip()
                        acct = ln.locator('span').first.inner_text().strip()
                        got.append((acct, side, amt, cur))
                    exp = q("""select a.name_ar, jl.debit, jl.credit, jl.currency_code from journal_lines jl join accounts a on a.id=jl.account_id
                               join journal_entries e on e.id=jl.entry_id where e.entry_no=:n order by jl.line_no""", n=entry_no)
                    exp_l = [(nm, 'debit' if d > 0 else 'credit', fmt(d if d > 0 else c, decs[cur]), cur) for nm, d, c, cur in exp]
                    if sorted(got) != sorted(exp_l):
                        mism.append(('journal-list: سطور القيد تختلف بين الشاشة والقاعدة', entry_no, got, exp_l))
                    else:
                        checked += 1
                    row.locator('.activity-item').click()
                ui['journal_entries_verified_equal'] = checked
                shown_nos = set()
                for i in range(n_rows):
                    pass
                allp = q("""select e.entry_no, e.operation_type, e.entry_date, e.status, e.reverses_entry_id, e.replaces_entry_id from journal_entries e where e.status='POSTED' order by e.id""")
                txt = pg.inner_text('.activity-list')
                ui['posted_entries_not_in_day_list'] = [(n, t, str(d), rv, rp) for n, t, d, st_, rv, rp in allp if n not in txt and not any(n in x for x in [txt])][:20]
                ui['journal_text_sample'] = pg.inner_text('.activity-list')[:1500]
                pg.screenshot(path=f'{OUT}/ui_journal.png')
            except Exception:
                ui['journal_error'] = traceback.format_exc()[-600:]

            # ---------- ٢) العملاء: رصيد + كشف حساب
            try:
                c1 = state['c1']
                code = q('select code from clients where id=:i', i=c1)[0][0]
                pg.click("button[title^='العملاء']")
                pg.wait_for_selector('.clients-screen', timeout=20000)
                pg.wait_for_timeout(800)
                inp = pg.locator('.clients-screen input').first
                inp.fill(code)
                pg.wait_for_timeout(1200)
                pg.locator('.clients-row', has_text=code).first.click()
                pg.wait_for_selector('.client-balances', timeout=20000)
                pg.wait_for_timeout(1200)
                ui['client_page_text'] = pg.inner_text('.clients-screen')[:1800]
                # عملة نشطة افتراضياً + إجمالي
                names = {'LYD': 'دينار ليبي', 'USD': 'دولار أمريكي'}
                for ccy in ('LYD', 'USD'):
                    try:
                        pg.get_by_role('tab', name=names[ccy]).first.click(timeout=3000)
                        pg.wait_for_timeout(900)
                        pg.select_option('.clients-screen select', label='طرابلس')
                        pg.wait_for_timeout(1200)
                    except Exception as e_:
                        ui.setdefault('tab_click_errors', []).append((ccy, str(e_)[:120]))
                    tot = pg.locator('.client-balance-total .num').first.inner_text().strip()
                    exp_tot = q("""select coalesce(sum(ab.balance),0) from accounts a join account_balances ab on ab.account_id=a.id
                                   where a.client_id=:c and a.currency_code=:cur""", c=c1, cur=ccy)[0][0]
                    ui.setdefault('client_totals', {})[ccy] = dict(shown=tot, db=fmt(exp_tot, decs[ccy]))
                    if tot != fmt(exp_tot, decs[ccy]):
                        mism.append(('client: الإجمالي المعروض', ccy, tot, fmt(exp_tot, decs[ccy])))
                    rows = pg.locator('table.data-table tbody tr')
                    shown = []
                    for i in range(rows.count()):
                        tds = rows.nth(i).locator('td')
                        if tds.count() < 8:
                            continue
                        shown.append([tds.nth(k).inner_text().strip() for k in range(8)])
                    ui.setdefault('statement_rows_shown', {})[ccy] = shown[:30]
                    # الكشف المتوقع من القاعدة: سطور حساب العميل (بالموقع الظاهر) مرتبة
                    loc_codes = [r[0] for r in q("select code from locations")]
                    exp_rows = q("""select e.entry_no, jl.debit, jl.credit, a.code from journal_lines jl join accounts a on a.id=jl.account_id
                                    join journal_entries e on e.id=jl.entry_id
                                    where a.client_id=:c and a.currency_code=:cur order by e.entry_date, e.id, jl.line_no""", c=c1, cur=ccy)
                    ui.setdefault('statement_expected_count', {})[ccy] = len(exp_rows)
                    ui.setdefault('statement_shown_count', {})[ccy] = len(shown)
                pg.screenshot(path=f'{OUT}/ui_client.png', full_page=True)
                ui['operation_type_cell_sample'] = [r[2] for r in ui.get('statement_rows_shown', {}).get('LYD', [])[:6]]
            except Exception:
                ui['client_error'] = traceback.format_exc()[-700:]

            # ---------- ٣) مركز السيولة مقابل القاعدة
            try:
                pg.click("button[title^='مركز السيولة']")
                pg.wait_for_selector('.liquidity-row', timeout=20000)
                pg.wait_for_timeout(600)
                shown = []
                rws = pg.locator('.liquidity-row')
                for i in range(rws.count()):
                    tds = rws.nth(i).locator('td')
                    shown.append([tds.nth(k).inner_text().strip() for k in range(4)])
                ui['liquidity_rows_shown'] = shown
                exp = q("""select a.currency_code, l.name_ar, a.type, coalesce(sum(ab.balance),0)
                           from accounts a join locations l on l.id=a.location_id left join account_balances ab on ab.account_id=a.id
                           where a.currency_code is not null group by a.currency_code, l.name_ar, a.type order by 1,2""")
                ui['liquidity_db_groups'] = [(c, n, t, str(b)) for c, n, t, b in exp]
            except Exception:
                ui['liquidity_error'] = traceback.format_exc()[-500:]

            # ---------- ٤) زيارة كل شاشة وتسجيل أخطاء الكونسول وطلبات الشبكة الفاشلة
            visited = {}
            for title in ('لوحة التحكم', 'الحسابات', 'التقارير', 'المطابقة', 'الإعدادات'):
                try:
                    pg.click(f"button[title^='{title}']")
                    pg.wait_for_timeout(1500)
                    visited[title] = len(pg.inner_text('main, .app-main, body')) if True else 0
                except Exception as e:
                    visited[title] = f'ERR {str(e)[:100]}'
            ui['screens_visited_text_len'] = visited
            ui['console_errors'] = console[:25]
            ui['http_errors_seen_by_browser'] = bad[:30]
            ui['non_get_requests_seen'] = reqs[:30]
            for lab in ('الإعدادات',):
                pass
        finally:
            browser.close()
