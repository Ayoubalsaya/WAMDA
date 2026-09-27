const clients = [
  { name: 'شركة المدار للتجارة', code: 'CL-1024', initial: 'م', tag: 'عميل نشط', credit: 'حد ائتماني 10,000 LYD' },
  { name: 'أحمد مختار', code: 'CL-1148', initial: 'أ', tag: 'فردي', credit: 'رصيد موثّق' },
  { name: 'مؤسسة النور', code: 'CL-1206', initial: 'ن', tag: 'عميل نشط', credit: 'حساب متعدد العملات' },
  { name: 'سارة السنوسي', code: 'CL-1312', initial: 'س', tag: 'فردي', credit: 'آخر حركة اليوم' },
]

const activities = [
  { type: 'incoming', icon: '↓', title: 'قبض', client: 'شركة المدار للتجارة', amount: '+ 8,500.000', currency: 'LYD', status: 'posted', time: '10:42 ص' },
  { type: 'exchange', icon: '⇄', title: 'صرافة', client: 'أحمد مختار', amount: '2,000.00', currency: 'USD', status: 'posted', time: '10:18 ص' },
  { type: 'outgoing', icon: '↑', title: 'صرف', client: 'مؤسسة النور', amount: '− 1,240.000', currency: 'LYD', status: 'pending', time: '09:56 ص' },
  { type: 'transfer', icon: '↗', title: 'تحويل بعمولة', client: 'سارة السنوسي', amount: '+ 3,100.000', currency: 'LYD', status: 'posted', time: '09:31 ص' },
  { type: 'incoming', icon: '↓', title: 'قبض', client: 'حساب داخلي', amount: '+ 12,000.000', currency: 'LYD', status: 'pending', time: '09:05 ص' },
  { type: 'outgoing', icon: '↑', title: 'مصروف', client: 'مصروف تشغيلي', amount: '− 320.000', currency: 'LYD', status: 'posted', time: '08:42 ص' },
]

const operationNames = { RECEIPT: 'قبض', PAYMENT: 'صرف', EXCHANGE: 'صرافة', CASH_TRANSFER: 'تحويل بعمولة', EXPENSE: 'مصروف', REMIT_OUT: 'إرسال لمستفيد' }
const operationLabels = { RECEIPT: 'الحساب المستقبِل', PAYMENT: 'الحساب المصروف منه', EXCHANGE: 'الحساب المصدر', CASH_TRANSFER: 'حساب المصدر' }
let selectedClient = null
let activeOperation = 'RECEIPT'

const qs = (selector, root = document) => root.querySelector(selector)
const qsa = (selector, root = document) => [...root.querySelectorAll(selector)]
const show = (el) => { if (el) el.hidden = false }
const hide = (el) => { if (el) el.hidden = true }

function toast(message, kind = 'success') {
  const stack = qs('#toastStack')
  const item = document.createElement('div')
  item.className = `toast ${kind}`
  item.innerHTML = `<span class="toast-icon">${kind === 'success' ? '✓' : '!'}</span><span>${message}</span>`
  stack.append(item)
  window.setTimeout(() => { item.style.opacity = '0'; item.style.transform = 'translateX(-15px)'; item.style.transition = 'all .25s ease'; window.setTimeout(() => item.remove(), 260) }, 3200)
}

function renderActivities(filter = 'all') {
  const list = qs('#activityList')
  const rows = filter === 'all' ? activities : activities.filter((row) => row.status === filter)
  list.innerHTML = rows.slice(0, 6).map((row) => `
    <button class="activity-item is-${row.status}" data-client="${row.client}">
      <span class="activity-icon ${row.type}">${row.icon}</span>
      <span class="activity-copy"><strong>${row.title}</strong><small>${row.client} · ${row.time}</small></span>
      <span class="activity-amount"><strong>${row.amount}</strong><small>${row.currency}</small></span>
    </button>`).join('')
  qsa('.activity-item', list).forEach((item) => item.addEventListener('click', () => {
    const name = item.dataset.client
    const client = clients.find((candidate) => candidate.name === name)
    if (client) selectClient(client)
    toast(`تم فتح تفاصيل عملية ${name}`)
  }))
}

function renderClientResults(query) {
  const results = qs('#clientResults')
  const normalized = query.trim().toLowerCase()
  const matches = clients.filter((client) => `${client.name} ${client.code}`.toLowerCase().includes(normalized))
  if (!normalized) { hide(results); return }
  results.innerHTML = matches.length ? matches.map((client) => `<button class="client-result" data-client-code="${client.code}"><span><strong>${client.name}</strong><small>${client.credit}</small></span><small>${client.code}</small></button>`).join('') : '<div class="client-result"><span><strong>لا توجد نتائج</strong><small>جرّب اسماً أو كوداً مختلفاً</small></span></div>'
  show(results)
  qsa('[data-client-code]', results).forEach((button) => button.addEventListener('click', () => {
    const client = clients.find((candidate) => candidate.code === button.dataset.clientCode)
    if (client) selectClient(client)
  }))
}

function selectClient(client) {
  selectedClient = client
  const box = qs('#selectedClient')
  box.innerHTML = `<div class="client-profile"><span class="avatar avatar-client">${client.initial}</span><span><strong>${client.name}</strong><small>${client.code}</small></span><button class="client-clear" id="innerClearClient" aria-label="مسح العميل">×</button></div><div class="client-tags"><span class="client-tag">${client.tag}</span><span class="client-tag">${client.credit}</span></div>`
  show(qs('#balancePanel'))
  hide(qs('#clientResults'))
  qs('#clientSearch').value = client.name
  qs('#entryPreview').innerHTML = `<div class="preview-icon">✓</div><div><strong>${client.name} جاهز للعملية</strong><span>أدخل المبلغ لتظهر لك المعاينة قبل الترحيل.</span></div><span class="preview-arrow">←</span>`
  qs('#innerClearClient').addEventListener('click', clearClient)
  toast(`تم اختيار ${client.name}`)
}

function clearClient() {
  selectedClient = null
  qs('#clientSearch').value = ''
  qs('#selectedClient').innerHTML = '<div class="empty-client"><span class="empty-client-icon">♙</span><strong>لا يوجد عميل محدد</strong><span>اختيار العميل يجعل المعاينة والرصيد أكثر دقة.</span><button type="button" id="emptyChoose">اختيار عميل <b>←</b></button></div>'
  qs('#emptyChoose')?.addEventListener('click', () => qs('#clientSearch').focus())
  hide(qs('#balancePanel'))
  qs('#entryPreview').innerHTML = '<div class="preview-icon">✦</div><div><strong>معاينة القيد</strong><span>اختر العميل وأدخل المبلغ لعرض الأثر المالي قبل الترحيل.</span></div><span class="preview-arrow">←</span>'
}

function setOperation(operation, closeModal = true) {
  activeOperation = operation
  qsa('.operation-tab').forEach((tab) => tab.classList.toggle('is-active', tab.dataset.operation === operation))
  qs('#entryTitle').textContent = `إضافة عملية ${operationNames[operation] || 'جديدة'}`
  qs('#accountLabel').textContent = operationLabels[operation] || 'الحساب المستقبِل'
  if (operation === 'EXCHANGE') qs('#entryPreview').innerHTML = '<div class="preview-icon">⇄</div><div><strong>مسار الصرافة جاهز</strong><span>اختر عملة الوجهة لإكمال التحويل بين العملتين.</span></div><span class="preview-arrow">←</span>'
  if (closeModal) closeCreate()
  qs('#entryForm').animate([{ opacity: .62, transform: 'translateY(5px)' }, { opacity: 1, transform: 'none' }], { duration: 280, easing: 'cubic-bezier(.22,1,.36,1)' })
  toast(`تم تجهيز نموذج ${operationNames[operation] || 'العملية'}`)
}

function openCreate() { show(qs('#createModal')); document.body.classList.add('modal-open') }
function closeCreate() { hide(qs('#createModal')); document.body.classList.remove('modal-open') }

function bindButtonRipples() {
  document.addEventListener('click', (event) => {
    const button = event.target.closest('button')
    if (!button || button.disabled) return
    const ripple = document.createElement('span')
    ripple.className = 'click-ripple'
    button.append(ripple)
    window.setTimeout(() => ripple.remove(), 460)
  })
}

function initSearch() {
  const input = qs('#globalSearch')
  const results = qs('#searchResults')
  const render = () => {
    const query = input.value.trim()
    if (!query) { hide(results); return }
    const matches = [...clients.map((client) => ({ title: client.name, meta: `عميل · ${client.code}`, icon: '♙' })), ...activities.slice(0, 3).map((row) => ({ title: `${row.title} — ${row.amount} ${row.currency}`, meta: `عملية · ${row.time}`, icon: row.icon }))].filter((row) => `${row.title} ${row.meta}`.toLowerCase().includes(query.toLowerCase())).slice(0, 5)
    results.innerHTML = matches.length ? matches.map((row) => `<button class="search-result"><span class="search-result-icon">${row.icon}</span><span><strong>${row.title}</strong><small>${row.meta}</small></span></button>`).join('') : '<div class="search-result"><span><strong>لا توجد نتائج</strong><small>جرّب كلمة أخرى</small></span></div>'
    show(results)
  }
  input.addEventListener('input', render)
  input.addEventListener('keydown', (event) => { if (event.key === 'Escape') { input.value = ''; hide(results); input.blur() } })
  document.addEventListener('click', (event) => { if (!event.target.closest('.command-search')) hide(results) })
}

function init() {
  renderActivities()
  initSearch()
  bindButtonRipples()
  qsa('.rail-link').forEach((item) => item.addEventListener('click', () => {
    qsa('.rail-link').forEach((nav) => nav.classList.remove('is-active'))
    item.classList.add('is-active')
    if (item.dataset.screen !== 'journal') toast(`${item.querySelector('small').textContent} — هذه نسخة تصميمية للمعاينة`, 'success')
  }))
  ;['#openCreate', '#openCreateHeader'].forEach((selector) => qs(selector).addEventListener('click', openCreate))
  qs('#closeCreate').addEventListener('click', closeCreate)
  qs('#createModal').addEventListener('click', (event) => { if (event.target.id === 'createModal') closeCreate() })
  qsa('#operationGrid button').forEach((button) => button.addEventListener('click', () => setOperation(button.dataset.operation)))
  qsa('.operation-tab').forEach((tab) => tab.addEventListener('click', () => tab.dataset.operation ? setOperation(tab.dataset.operation, false) : openCreate()))
  qs('#clientSearch').addEventListener('input', (event) => renderClientResults(event.target.value))
  qs('#clearClient').addEventListener('click', clearClient)
  qs('#emptyChoose').addEventListener('click', () => qs('#clientSearch').focus())
  qs('#clearComposer').addEventListener('click', () => { qs('#entryForm').reset(); clearClient(); toast('تم تنظيف مساحة العملية') })
  qs('#todayButton').addEventListener('click', () => { qs('#entryDate').value = '2026-09-24'; toast('تم ضبط التاريخ على اليوم') })
  qs('#resetForm').addEventListener('click', () => { qs('#entryForm').reset(); clearClient(); toast('تم تنظيف النموذج') })
  qs('#entryForm').addEventListener('submit', (event) => { event.preventDefault(); const amount = qs('#amount').value.trim(); if (!selectedClient) { toast('اختر عميلاً أولاً لإكمال العملية', 'error'); qs('#clientSearch').focus(); return } if (!amount) { toast('أدخل مبلغ العملية أولاً', 'error'); qs('#amount').focus(); return } toast(`تم حفظ عملية ${operationNames[activeOperation]} للعميل ${selectedClient.name}`); qs('#entryPreview').innerHTML = '<div class="preview-icon">✓</div><div><strong>تم تجهيز العملية للترحيل</strong><span>تم حفظ المعاينة بنجاح — يمكنك بدء عملية أخرى فوراً.</span></div><span class="preview-arrow">✓</span>'; qs('#amount').value = '' })
  qs('#notificationButton').addEventListener('click', () => { const popover = qs('#notificationPopover'); const wasHidden = popover.hidden; popover.hidden = !wasHidden; qs('#notificationButton').setAttribute('aria-expanded', String(wasHidden)) })
  qs('#markRead').addEventListener('click', () => { qs('.notification-count').textContent = '0'; qs('.notification-count').style.background = 'var(--green)'; toast('تم تحديث قائمة التنبيهات') })
  qs('#focusSearch').addEventListener('click', () => qs('#globalSearch').focus())
  qs('#focusToggle').addEventListener('click', () => { document.body.classList.toggle('focus-mode'); const active = document.body.classList.contains('focus-mode'); toast(active ? 'تم تفعيل وضع التركيز' : 'تمت استعادة لوحات السياق'); qs('#focusToggle').setAttribute('aria-pressed', String(active)) })
  qs('#previousDay').addEventListener('click', () => toast('تم عرض اليوم السابق'))
  qs('#nextDay').addEventListener('click', () => toast('تم عرض اليوم التالي'))
  qs('#currency').addEventListener('change', (event) => { qs('#amountCurrency').textContent = event.target.value; toast(`تم تغيير العملة إلى ${event.target.value}`) })
  qsa('.activity-filters button').forEach((button) => button.addEventListener('click', () => { qsa('.activity-filters button').forEach((item) => item.classList.remove('is-active')); button.classList.add('is-active'); renderActivities(button.dataset.filter) }))
  qs('#refreshActivity').addEventListener('click', () => { renderActivities(); toast('تم تحديث سجل العمليات') })
  qs('#viewAll').addEventListener('click', () => toast('تم فتح عرض السجل الكامل — هذه نسخة معاينة مستقلة'))
  qs('#filterButton').addEventListener('click', () => toast('خيارات التصفية جاهزة للتخصيص'))
  qs('#moreTools').addEventListener('click', () => toast('المزيد من الأدوات سيظهر هنا في النسخة المتصلة'))
  qs('#viewClient').addEventListener('click', () => toast('تم فتح كشف العميل — هذه نسخة معاينة مستقلة'))
  qs('.dismiss-note').addEventListener('click', (event) => event.currentTarget.closest('.form-guide').remove())
  document.addEventListener('keydown', (event) => {
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)
    if (event.key === 'Escape') closeCreate()
    if (event.ctrlKey && event.key.toLowerCase() === 'n') { event.preventDefault(); openCreate() }
    if (event.key === '/' && !typing) { event.preventDefault(); qs('#globalSearch').focus() }
    if (event.altKey && /^[1-6]$/.test(event.key)) { const target = qs(`[data-shortcut="${event.key}"]`); if (target) target.click() }
  })
}

init()
