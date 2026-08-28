import csv, random, os
from datetime import date, timedelta

OUT = os.path.dirname(os.path.abspath(__file__))
random.seed(20260828)
BASE = date(2026, 9, 1)

VENDORS = [
 ('Acme Traders','ACME TRADERS PVT LTD'),('Bluewave Logistics','BLUEWAVE LOGISTICS'),
 ('Crestline Foods','CRESTLINE FOODS INDIA'),('Delta Textiles','DELTA TEXTILE MILLS'),
 ('Everline Media','EVERLINE MEDIA GROUP'),('Falcon Freight','FALCON FREIGHT SERVICES'),
 ('Greenfield Farms','GREENFIELD FARMS CO'),('Horizon Retail','HORIZON RETAIL LTD'),
 ('Indigo Health','INDIGO HEALTHCARE'),('Jupiter Electronics','JUPITER ELECTRONICS PVT LTD'),
 ('Kestrel Analytics','KESTREL ANALYTICS LLP'),('Lumen Energy','LUMEN ENERGY SOLUTIONS'),
 ('Meridian Pharma','MERIDIAN PHARMACEUTICALS'),('Novastar Apparel','NOVASTAR APPAREL CO'),
 ('Oakridge Furniture','OAKRIDGE FURNITURE WORKS'),('Pinecrest Consulting','PINECREST CONSULTING GRP'),
]

bank=[]; processor=[]; erp=[]; key=[]; manifest=[]
seq={'PAY':2000,'BANK':3000,'JNL':4000,'ORD':5000,'INV':6000,'SET':7000,'UTR':8000}
def nid(prefix): seq[prefix]+=1; return f'{prefix}{seq[prefix]}'
def ds(n): return (BASE+timedelta(days=n)).isoformat()
def add_key(source,tid,ms=None,mids=None,exc=''):
    key.append({'source':source,'transaction_id':tid,'expected_match_source':ms or '', 'expected_match_ids':';'.join(mids or []), 'expected_exception_type':exc})
def add_manifest(case,ids,description): manifest.append({'case_id':case,'transaction_ids':';'.join(ids),'description':description})
def add_p(gross,fee,refund,order,customer,settlement='',day=0,status='captured', pay_id=None):
    pay_id=pay_id or nid('PAY'); net=round(gross-fee-refund,2)
    processor.append({'payment_id':pay_id,'order_id':order,'customer_id':customer,'payment_date':ds(day),'gross_amount':gross,'fee':fee,'refund':refund,'net_amount':net,'settlement_id':settlement,'currency':'INR','status':status})
    return pay_id,net
def add_b(amount,ref,desc,day=1,currency='INR',bid=None):
    bid=bid or nid('BANK'); bank.append({'transaction_id':bid,'transaction_date':ds(day),'value_date':ds(day),'amount':amount,'currency':currency,'reference':ref,'description':desc}); return bid
def add_e(inv,amount,ref,day=2,currency='INR',cp='',account='Accounts Receivable',debit=0,credit=None,jid=None):
    jid=jid or nid('JNL'); credit=amount if credit is None else credit
    erp.append({'journal_id':jid,'invoice_id':inv,'posting_date':ds(day),'account':account,'debit':debit,'credit':credit,'amount':amount,'currency':currency,'reference':ref,'counterparty':cp}); return jid

# ================= ORIGINAL CATEGORY SET (rebuilt, scaled) =================

# 1) 1:1 exact identity: 36
for i in range(36):
    v,va=VENDORS[i%len(VENDORS)]; gross=round(random.uniform(5000,75000),2); fee=round(gross*0.015,2); order=nid('ORD')
    p,net=add_p(gross,fee,0,order,v); b=add_b(net,p,f'SETTLEMENT PAYOUT {p}',1); e=add_e(order,net,p,2,cp=v)
    add_key('processor',p,'bank',[b]); add_key('bank',b,'erp',[e])
    add_manifest('EXACT_1_TO_1',[p,b,e],'Exact reference, amount, currency and expected settlement timing.')

# 2) fee-aware: 16
for i in range(16):
    v,_=VENDORS[(i+2)%len(VENDORS)]; gross=round(random.uniform(10000,80000),2); fee=round(gross*0.018,2); order=nid('ORD')
    p,net=add_p(gross,fee,0,order,v); b=add_b(net,p,f'NET SETTLEMENT {p}',1); e=add_e(order,gross,p,2,cp=v)
    add_key('processor',p,'bank',[b]); add_key('bank',b,'erp',[e])
    add_manifest('FEE_AWARE',[p,b,e],'Bank settles net of processor fee; ERP records gross receivable.')

# 3) timing gap: 12
for i in range(12):
    v,_=VENDORS[(i+4)%len(VENDORS)]; gross=round(random.uniform(7000,25000),2); order=nid('ORD'); p,net=add_p(gross,0,0,order,v)
    b=add_b(net,p,f'PAYOUT {p}',3); add_key('processor',p,'bank',[b])
    add_manifest('TIMING_GAP',[p,b],'Settlement arrives three days after payment; valid within configured tolerance.')

# 4) fuzzy name drift: 14
fuzzy=['ACME TRADERS','Bluewave Logisitcs','CRESTLINE FOODS INDIA','DELTA TEXTILE MILLS','EVERLINE MEDIA GROUP',
       'FALCON FRT SVCS','GREENFIELD FARM CO','HORIZON RETAIL LIMITED','INDIGO HEALTHCARE LTD','JUPITER ELECTRONIC PVT LTD',
       'KESTREL ANALYTIC LLP','LUMEN ENRGY SOLTNS','MERIDIAN PHARMA CO','NOVASTAR APPARELS CO']
for i in range(14):
    v,_=VENDORS[i]; gross=round(random.uniform(6000,22000),2); order=nid('ORD'); p,net=add_p(gross,0,0,order,v)
    b=add_b(net,nid('UTR'),f'{fuzzy[i]} PAYOUT',0)
    add_key('processor',p,'bank',[b])
    add_manifest('FUZZY_NAME_DRIFT',[p,b],'No shared reference; counterparty/description differs by abbreviation, typo or formatting.')

# 5) semantic-only: 8
sem=[('Office stationery vendor','PAYMENT TO STATIONERY SUPPLIER'),('Cloud infra provider','MONTHLY CLOUD HOSTING CHARGE'),
     ('Courier partner','LOGISTICS AND COURIER PAYOUT'),('Marketing agency','DIGITAL ADS CAMPAIGN SETTLEMENT'),
     ('Insurance broker','CORPORATE INSURANCE PREMIUM'),('Facilities contractor','OFFICE MAINTENANCE SERVICES'),
     ('Legal counsel retainer','OUTSIDE COUNSEL MONTHLY RETAINER'),('Recruitment agency','HIRING PARTNER PLACEMENT FEE')]
for a,bdesc in sem:
    gross=round(random.uniform(5000,18000),2); order=nid('ORD'); p,net=add_p(gross,0,0,order,a)
    b=add_b(net,nid('UTR'),bdesc,0)
    add_key('processor',p,'bank',[b])
    add_manifest('SEMANTIC_MATCH',[p,b],'Different wording requires semantic interpretation; amount and timing remain consistent.')

# 6) many-to-one settlements: 7 batches x 4 payments
for s in range(7):
    sid=nid('SET'); pids=[]; total=0
    for j in range(4):
        v,_=VENDORS[(s+j)%len(VENDORS)]; gross=round(random.uniform(3000,15000),2); fee=round(gross*.02,2); order=nid('ORD')
        p,net=add_p(gross,fee,0,order,v,sid); pids.append(p); total+=net
    total=round(total,2); b=add_b(total,sid,f'BATCH SETTLEMENT {sid}',1); e=add_e(sid,total,sid,2,cp='Settlement Batch')
    for p in pids: add_key('processor',p,'bank',[b])
    add_key('bank',b,'erp',[e])
    add_manifest('MANY_TO_ONE',[*pids,b,e],'Four processor payments aggregate into one bank settlement and one ERP settlement journal.')

# 7) one-to-many fully paid invoice: 5
for i in range(5):
    v,_=VENDORS[(i+3)%len(VENDORS)]; inv=nid('INV'); total=round(random.uniform(40000,90000),2); e=add_e(inv,total,inv,0,cp=v)
    a=round(total*.4,2); b1=add_b(a,inv,f'PART PAYMENT {inv} A',1); b2=add_b(round(total-a,2),inv,f'PART PAYMENT {inv} B',2)
    add_key('erp',e,'bank',[b1,b2])
    add_manifest('ONE_TO_MANY_FULL',[e,b1,b2],'One ERP invoice is fully settled by two bank credits.')

# 8) partial + overpaid invoice: 4 each
for i in range(4):
    v,_=VENDORS[(i+6)%len(VENDORS)]; inv=nid('INV'); total=round(random.uniform(50000,100000),2); e=add_e(inv,total,inv,0,cp=v)
    b1=add_b(round(total*.3,2),inv,f'PART PAYMENT {inv} A',1); b2=add_b(round(total*.2,2),inv,f'PART PAYMENT {inv} B',2)
    add_key('erp',e,None,None,'partially_paid')
    add_manifest('PARTIAL_PAYMENT',[e,b1,b2],'ERP invoice exceeds total received bank credits; should remain partially paid.')
for i in range(4):
    v,_=VENDORS[(i+2)%len(VENDORS)]; inv=nid('INV'); total=round(random.uniform(30000,60000),2); e=add_e(inv,total,inv,0,cp=v)
    b1=add_b(round(total*.65,2),inv,f'PAYMENT {inv} A',1); b2=add_b(round(total*.55,2),inv,f'PAYMENT {inv} B',2)
    add_key('erp',e,None,None,'overpaid')
    add_manifest('OVERPAID',[e,b1,b2],'Bank credits exceed ERP invoice amount.')

# 9) amount mismatch: 10
for i in range(10):
    v,_=VENDORS[i%len(VENDORS)]; gross=round(random.uniform(7000,30000),2); order=nid('ORD'); p,net=add_p(gross,0,0,order,v)
    b=add_b(round(net-random.uniform(100,900),2),p,f'PAYOUT {p} ADJUSTED',0)
    add_key('processor',p,None,None,'amount_mismatch')
    add_manifest('AMOUNT_MISMATCH',[p,b],'Reference is plausible but bank amount differs beyond tolerance with no explainable fee/refund.')

# 10) missing bank counterpart: 8
for i in range(8):
    v,_=VENDORS[i%len(VENDORS)]; gross=round(random.uniform(4000,25000),2); order=nid('ORD')
    p,net=add_p(gross,0,0,order,v,status='pending_settlement')
    add_key('processor',p,None,None,'missing_counterpart')
    add_manifest('MISSING_BANK',[p],'Captured processor payment has no corresponding bank settlement.')

# 11) unidentified cash: 8
for i in range(8):
    amt=round(random.uniform(2000,20000),2); b=add_b(amt,nid('UTR'),'UNIDENTIFIED NEFT CREDIT',0)
    add_key('bank',b,None,None,'unidentified_cash')
    add_manifest('UNIDENTIFIED_CASH',[b],'Bank credit has no processor or ERP counterpart.')

# 12) duplicates (genuinely ambiguous — should stay in review): 6
for i in range(6):
    v,_=VENDORS[i]; gross=round(random.uniform(7000,22000),2); order=nid('ORD'); p,net=add_p(gross,0,0,order,v)
    b1=add_b(net,nid('UTR'),v.upper(),0); b2=add_b(net,nid('UTR'),v.upper()+' ',0)
    add_key('processor',p,None,None,'duplicate')
    add_manifest('DUPLICATE_CANDIDATES',[p,b1,b2],'Two equally plausible bank candidates exist; engine must not consume both.')

# 13) refund lifecycle: 6 matched, 4 missing, 3 duplicate
for i in range(6):
    v,_=VENDORS[i]; gross=round(random.uniform(8000,30000),2); fee=round(gross*.015,2); refund=round(gross*.25,2); order=nid('ORD')
    p,net=add_p(gross,fee,refund,order,v); sb=add_b(net,p,f'SETTLEMENT PAYOUT {p}',1); rb=add_b(-refund,f'RF-{p}',f'REFUND DEBIT {p}',2)
    add_key('processor',p,'bank',[sb]); add_key('bank',rb,'processor',[p])
    add_manifest('REFUND_MATCHED',[p,sb,rb],'Processor refund has matching bank debit plus settlement.')
for i in range(4):
    v,_=VENDORS[(i+5)%len(VENDORS)]; gross=round(random.uniform(8000,25000),2); refund=round(gross*.3,2); order=nid('ORD')
    p,net=add_p(gross,0,refund,order,v); sb=add_b(net,p,f'SETTLEMENT PAYOUT {p}',1)
    add_key('processor',p,'bank',[sb]); add_key('processor',p,None,None,'refund_missing_from_bank')
    add_manifest('REFUND_MISSING',[p,sb],'Processor reports refund but bank refund debit is absent.')
for i in range(3):
    v,_=VENDORS[(i+1)%len(VENDORS)]; gross=round(random.uniform(8000,25000),2); refund=round(gross*.2,2); order=nid('ORD')
    p,net=add_p(gross,0,refund,order,v); sb=add_b(net,p,f'SETTLEMENT PAYOUT {p}',1)
    r1=add_b(-refund,f'RF-{p}-A',f'REFUND DEBIT {p}',2); r2=add_b(-refund,f'RF-{p}-B',f'REFUND DEBIT {p}',2)
    add_key('processor',p,'bank',[sb]); add_key('processor',p,None,None,'duplicate_refund')
    add_manifest('REFUND_DUPLICATE',[p,sb,r1,r2],'Two bank refund debits appear for one processor refund.')

# 14) manual-entry/data-quality cases: 6
for i in range(6):
    v,_=VENDORS[(i+3)%len(VENDORS)]; gross=round(random.uniform(6000,25000),2); order=nid('ORD'); p,net=add_p(gross,0,0,order,v)
    if i==0: entered=round(net/10,2); reason='manual_amount_entry_error'
    elif i==1: entered=net; reason='manual_date_entry_error'
    elif i==2: entered=net; reason='manual_reference_typo'
    elif i==3: entered=net; reason='manual_counterparty_typo'
    elif i==4: entered=net; reason='manual_duplicate_entry'
    else: entered=net; reason='manual_missing_reference'
    ref=p; desc=v; day=1
    if i==1: day=3
    if i==2: ref=p[:-1]+'9'
    if i==3: desc=v.replace(' ','')
    if i==5: ref=''
    b=add_b(entered,ref,desc,day)
    exc='amount_mismatch' if i==0 else ('duplicate' if i==4 else 'manual_data_quality_exception')
    add_key('processor',p,None,None,exc)
    add_manifest('MANUAL_ENTRY_'+reason.upper(),[p,b],'Synthetic manual-entry error: '+reason.replace('_',' ')+'.')

v,_=VENDORS[9]; gross=15000.00; order=nid('ORD'); p,net=add_p(gross,0,0,order,v); b1=add_b(net,p,v,1); b2=add_b(net,p,v,1)
add_key('processor',p,None,None,'duplicate')
add_manifest('MANUAL_DUPLICATE_ENTRY',[p,b1,b2],'Manual entry created the same bank transaction twice.')

# 15) currency mismatch: 4
for i in range(4):
    v,_=VENDORS[i]; gross=round(random.uniform(5000,18000),2); order=nid('ORD'); p,net=add_p(gross,0,0,order,v)
    b=add_b(net,p,f'PAYOUT {p}',1,'USD')
    add_key('processor',p,None,None,'currency_mismatch')
    add_manifest('CURRENCY_MISMATCH',[p,b],'Amount/reference look plausible but currencies conflict; must be rejected.')

# 16) ERP missing bank: 5
for i in range(5):
    v,_=VENDORS[(i+4)%len(VENDORS)]; inv=nid('INV'); amt=round(random.uniform(10000,50000),2); e=add_e(inv,amt,inv,0,cp=v)
    add_key('erp',e,None,None,'missing_counterpart')
    add_manifest('ERP_ONLY',[e],'ERP receivable has no bank/processor counterpart.')

# 17) bank/ERP exact cash receipts without processor: 5
for i in range(5):
    v,_=VENDORS[(i+1)%len(VENDORS)]; inv=nid('INV'); amt=round(random.uniform(10000,40000),2); e=add_e(inv,amt,inv,0,cp=v)
    b=add_b(amt,inv,f'DIRECT CUSTOMER CREDIT {v}',1)
    add_key('bank',b,'erp',[e]); add_key('erp',e,'bank',[b])
    add_manifest('DIRECT_BANK_ERP',[b,e],'Direct bank-to-ERP receipt with no processor record; demonstrates multi-source flexibility.')

# ================= NEW: CASES DESIGNED TO FORCE GENUINE LLM ADJUDICATION =================
# These are constructed so that pure rule-based matching (exact ref/amount) and simple
# fuzzy-string / embedding thresholds are insufficient on their own — resolving them
# correctly requires contextual reasoning across multiple weak signals at once
# (partial reference fragments + narrative context + arithmetic + plausible-but-imperfect
# name overlap), which is exactly the job of an LLM adjudication step.

# 18) LLM_PARAPHRASE_PLUS_ROUNDING: heavy free-text paraphrase AND the bank amount is
# rounded to the nearest 10 (so exact-amount match fails too) — needs semantic read +
# tolerance reasoning together. 8 cases.
llm_para = [
 ('Acme Traders','Reimbursement settled to trading partner re: August purchase order'),
 ('Bluewave Logistics','Freight partner payout — logistics services rendered last cycle'),
 ('Kestrel Analytics','Vendor disbursement, data/analytics engagement, per SOW'),
 ('Lumen Energy','Utility partner settlement for energy services contract'),
 ('Meridian Pharma','Payout to pharma supply partner against PO fulfilment'),
 ('Novastar Apparel','Garment vendor payment, seasonal collection order'),
 ('Oakridge Furniture','Furnishings supplier settlement, showroom order batch'),
 ('Pinecrest Consulting','Advisory partner payout, quarterly engagement fee'),
]
for v, narrative in llm_para:
    gross = round(random.uniform(9000, 40000), 2)
    order = nid('ORD'); p, net = add_p(gross, 0, 0, order, v)
    rounded = round(net / 10) * 10  # rounding breaks exact-amount rule
    b = add_b(rounded, nid('UTR'), narrative, 1)
    add_key('processor', p, 'bank', [b])
    add_manifest('LLM_PARAPHRASE_PLUS_ROUNDING', [p, b],
                  'Bank narration is fully paraphrased AND amount is rounded to the nearest 10; requires joint semantic + tolerance reasoning beyond simple fuzzy/threshold rules.')

# 19) LLM_MULTI_CANDIDATE_DISAMBIGUATION: two bank rows are superficially similar, but only
# one is the CORRECT match once the narrative context (installment number, date proximity,
# customer-specific note) is read and reasoned about jointly with the amount. 7 cases.
for i in range(7):
    v, _ = VENDORS[i % len(VENDORS)]
    gross = round(random.uniform(10000, 30000), 2)
    order = nid('ORD'); p, net = add_p(gross, 0, 0, order, v)
    wrong_amt = round(net + random.choice([-1, 1]) * random.uniform(150, 450), 2)
    correct = add_b(net, nid('UTR'), f'{v.upper()} SECOND INSTALMENT REF ORDER {order[-3:]}', 1)
    decoy = add_b(wrong_amt, nid('UTR'), f'{v.upper()} FIRST INSTALMENT REF ORDER {order[-3:]}', 1)
    add_key('processor', p, 'bank', [correct])
    add_manifest('LLM_MULTI_CANDIDATE_DISAMBIGUATION', [p, correct, decoy],
                  'Two structurally similar bank rows exist for the same vendor; only narrative context (installment reference, near-exact amount) identifies the true match — the decoy must be rejected, not both accepted.')

# 20) LLM_INDIRECT_REFERENCE: bank narration references an internal PO/project/employee code
# instead of the order id; the true counterparty is only recoverable via the ERP counterparty
# name plus amount plus loose date reasoning (no processor row involved at all). 7 cases.
for i in range(7):
    v, _ = VENDORS[(i + 3) % len(VENDORS)]
    inv = nid('INV'); amt = round(random.uniform(12000, 55000), 2)
    e = add_e(inv, amt, inv, 0, cp=v)
    po_code = f'PO-{random.randint(4000,4999)}'
    b = add_b(amt, po_code, f'PAYMENT AGAINST {po_code} RAISED BY {v.upper()} PROCUREMENT DESK', 2)
    add_key('bank', b, 'erp', [e]); add_key('erp', e, 'bank', [b])
    add_manifest('LLM_INDIRECT_REFERENCE', [b, e],
                  'Bank narration cites an internal PO/project code rather than the invoice id; linking to the ERP receivable requires reading the counterparty mention inside free text, not a reference-field match.')

# 21) LLM_NOISY_OCR_TEXT: description simulates a garbled/abbreviated bank statement import
# (dropped vowels, truncated words, stray characters) that a plain fuzzy-match threshold
# would likely score too low to accept confidently. 6 cases.
noisy = [
 ('Acme Traders','ACM TRDRS PYT-PO#{o} NEFT/RTGS/xxxxx'),
 ('Everline Media','EVRLN MDIA GRP//SETLMNT-{o}//'),
 ('Falcon Freight','FLCN FRGHT SVC.. PYOUT#{o}..'),
 ('Greenfield Farms','GRNFLD FRMS CO_SETL_{o}_NEFT'),
 ('Horizon Retail','HRZN RTL LTD PYMNT REF {o} IMPS'),
 ('Indigo Health','INDG HLTHCR PYT-{o}-RTGS'),
]
for v, tmpl in noisy:
    gross = round(random.uniform(6000, 20000), 2)
    order = nid('ORD'); p, net = add_p(gross, 0, 0, order, v)
    b = add_b(net, nid('UTR'), tmpl.format(o=order[-4:]), 0)
    add_key('processor', p, 'bank', [b])
    add_manifest('LLM_NOISY_OCR_TEXT', [p, b],
                  'Bank description simulates garbled/abbreviated statement text (dropped vowels, truncated tokens); confident matching requires language-model-level text normalization, not simple string distance.')

# 22) LLM_CROSS_FIELD_ARITHMETIC: bank amount equals processor gross minus a locally-described
# deduction that is NOT in the standard fee field (e.g. "less TDS", "less courier chargeback")
# — the engine must read the narration to justify a non-standard amount delta. 6 cases.
deductions = [
    ('TDS deducted @2% as per Form 26AS', 0.02),
    ('courier RTO chargeback adjusted', None),
    ('bank service charge deducted', None),
    ('early settlement discount applied', None),
    ('GST TCS deducted at source', 0.01),
    ('penalty for late dispatch adjusted', None),
]
for i, (note, pct) in enumerate(deductions):
    v, _ = VENDORS[(i + 6) % len(VENDORS)]
    gross = round(random.uniform(15000, 45000), 2)
    order = nid('ORD'); p, net = add_p(gross, 0, 0, order, v)  # processor shows fee=0, net=gross
    if pct:
        deduction = round(gross * pct, 2)
    else:
        deduction = round(random.uniform(200, 1500), 2)
    bank_amt = round(gross - deduction, 2)
    b = add_b(bank_amt, p, f'SETTLEMENT {p} LESS {note.upper()}', 1)
    add_key('processor', p, 'bank', [b])
    add_manifest('LLM_CROSS_FIELD_ARITHMETIC', [p, b],
                  'Bank amount differs from the processor net amount by a non-standard, narration-only deduction (TDS/chargeback/discount/penalty) not captured in any structured fee field; requires reading the description to justify the delta before accepting the match.')

# 23) LLM_AMBIGUOUS_MANY_TO_ONE: a settlement batch narration lists a partial, reordered
# subset of payment references embedded in free text (not a clean delimited list), and the
# totals only reconcile once all fragments are correctly parsed and summed. 4 batches x 3 payments.
for s in range(4):
    sid = nid('SET'); pids = []; total = 0
    for j in range(3):
        v, _ = VENDORS[(s + j + 8) % len(VENDORS)]
        gross = round(random.uniform(4000, 16000), 2); order = nid('ORD')
        p, net = add_p(gross, 0, 0, order, v, sid); pids.append(p); total += net
    total = round(total, 2)
    frag = f"BATCH PAYOUT COVERING {pids[0]} & {pids[2]}, ALSO {pids[1]} (partial narration order)"
    b = add_b(total, sid, frag, 1)
    for p in pids:
        add_key('processor', p, 'bank', [b])
    add_manifest('LLM_AMBIGUOUS_MANY_TO_ONE', [*pids, b],
                  'Settlement narration lists constituent payment references out of order inside free text rather than a clean delimited field; correctly attributing all payments requires parsing the sentence, not splitting on a delimiter.')

# Sort for realism
for rows, field in [(processor, 'payment_id'), (bank, 'transaction_id'), (erp, 'journal_id')]:
    rows.sort(key=lambda r: r[field])

schemas = {
 'bank.csv': ['transaction_id','transaction_date','value_date','amount','currency','reference','description'],
 'processor.csv': ['payment_id','order_id','customer_id','payment_date','gross_amount','fee','refund','net_amount','settlement_id','currency','status'],
 'erp.csv': ['journal_id','invoice_id','posting_date','account','debit','credit','amount','currency','reference','counterparty'],
 'answer_key.csv': ['source','transaction_id','expected_match_source','expected_match_ids','expected_exception_type'],
 'case_manifest.csv': ['case_id','transaction_ids','description'],
}
data = {'bank.csv': bank, 'processor.csv': processor, 'erp.csv': erp, 'answer_key.csv': key, 'case_manifest.csv': manifest}
for fn, rows in data.items():
    with open(os.path.join(OUT, fn), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=schemas[fn]); w.writeheader(); w.writerows(rows)

print(f"bank.csv: {len(bank)} rows")
print(f"processor.csv: {len(processor)} rows")
print(f"erp.csv: {len(erp)} rows")
print(f"answer_key.csv: {len(key)} rows")
print(f"case_manifest.csv: {len(manifest)} rows")
