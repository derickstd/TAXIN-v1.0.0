/* Taxman256 — Main JS */
(function(){
'use strict';

/* ── Sidebar ── */
/* Handled by inline <script> in base.html */

/* ── Select2 init ── */
function initSelect2(){
  if(!window.jQuery||!jQuery.fn.select2)return;
  jQuery('select').filter(function(){
    var select=jQuery(this);
    return !select.hasClass('select2-hidden-accessible')
      && (select.is('.s2, .select2, [data-searchable]')
        || this.options.length>15);
  }).select2({theme:'bootstrap-5',allowClear:false,width:'100%',
    minimumResultsForSearch:0,
    placeholder:function(){return jQuery(this).data('ph')||'Search or select…';}});
  // service select: autofill price
  jQuery(document).on('select2:select','.s2-svc',function(e){
    var price=jQuery(e.params.data.element).data('price')||'',
        vat=jQuery(e.params.data.element).data('vat')||false,
        row=jQuery(this).closest('.li-row');
    if(price){
      var defaultPrice=row.find('.li-default').val(price)[0];
      if(window.formatMoneyInput)window.formatMoneyInput(defaultPrice);
      if(!row.find('.li-price').val()){
        var negotiatedPrice=row.find('.li-price').val(price)[0];
        if(window.formatMoneyInput)window.formatMoneyInput(negotiatedPrice);
      }
      row.find('.li-vat-badge').toggle(!!vat);
    }
    recalcTotal();
  });
  jQuery(document).on('input','.li-price',recalcTotal);
  jQuery(document).on('change','input[type=checkbox][name$="-DELETE"]',recalcTotal);
}

/* ── Monetary input formatting ── */
var MONEY_FIELD_NAME = /(?:^|[-_])(?:amount|price|fee|balance|inflow|outflow|subtotal|vat_total|grand_total|total_fee|auto_approve_under_amount|require_receipt_under_amount|outstanding_threshold|penalty_amount)(?:$|[-_])/i;

function isMoneyInput(input){
  if(!(input instanceof HTMLInputElement))return false;
  return input.dataset.moneyInput==='true'
    || (input.type==='number'&&MONEY_FIELD_NAME.test(input.name||input.id||''));
}

function formatMoneyValue(value){
  var raw=String(value==null?'':value).trim().replace(/,/g,'');
  if(!raw)return '';
  var sign=raw.charAt(0)==='-'?'-':'';
  raw=raw.replace(/-/g,'').replace(/[^\d.]/g,'');
  var decimal=raw.indexOf('.');
  var whole=decimal===-1?raw:raw.slice(0,decimal);
  var fraction=decimal===-1?'':raw.slice(decimal+1).replace(/\./g,'');
  if(!whole&&decimal===-1)return '';
  return sign+whole.replace(/\B(?=(\d{3})+(?!\d))/g,',')
    +(decimal===-1?'':'.'+fraction);
}

function formatMoneyInput(input){
  if(!isMoneyInput(input))return;
  if(input.dataset.moneyInput!=='true'){
    input.dataset.moneyInput='true';
    input.type='text';
    input.inputMode='decimal';
  }
  var cursor=input.selectionStart;
  var digitsBefore=cursor===null?null:input.value.slice(0,cursor).replace(/,/g,'').length;
  var formatted=formatMoneyValue(input.value);
  if(formatted===input.value)return;
  input.value=formatted;
  if(digitsBefore!==null&&document.activeElement===input){
    var newCursor=0;
    var seen=0;
    while(newCursor<formatted.length&&seen<digitsBefore){
      if(formatted.charAt(newCursor)!==',')seen++;
      newCursor++;
    }
    input.setSelectionRange(newCursor,newCursor);
  }
}

function initMoneyInputs(root){
  var fields=[];
  if(root instanceof HTMLInputElement)fields.push(root);
  if(root&&root.querySelectorAll){
    fields=fields.concat(Array.prototype.slice.call(
      root.querySelectorAll('input[type="number"],input[data-money-input="true"]'),
    ));
  }
  fields.forEach(function(input){
    if(isMoneyInput(input))formatMoneyInput(input);
  });
}

function validateMoneyInput(input){
  var value=input.value.replace(/,/g,'').trim();
  var error='';
  if(value){
    var numericValue=Number(value);
    if(!Number.isFinite(numericValue)){
      error='Enter a valid amount.';
    }else{
      var min=input.getAttribute('min');
      var max=input.getAttribute('max');
      var step=input.getAttribute('step');
      if(min!==null&&numericValue<Number(min)){
        error='Enter an amount of at least '+min+'.';
      }else if(max!==null&&numericValue>Number(max)){
        error='Enter an amount no greater than '+max+'.';
      }else if(step&&step!=='any'&&Number(step)>0){
        var base=min===null?0:Number(min);
        var units=(numericValue-base)/Number(step);
        if(Math.abs(units-Math.round(units))>1e-8){
          error='Enter an amount using increments of '+step+'.';
        }
      }
    }
  }
  input.setCustomValidity(error);
  return !error;
}

function normalizeMoneyInputs(form){
  if(!form||!form.querySelectorAll)return;
  initMoneyInputs(form);
  form.querySelectorAll('input[data-money-input="true"]').forEach(function(input){
    input.value=input.value.replace(/,/g,'').trim();
  });
}

function prepareMoneyForm(form){
  if(!form||!form.querySelectorAll)return true;
  initMoneyInputs(form);
  var fields=Array.prototype.slice.call(
    form.querySelectorAll('input[data-money-input="true"]'),
  );
  var firstInvalid=null;
  fields.forEach(function(input){
    if(!validateMoneyInput(input)&&!firstInvalid)firstInvalid=input;
  });
  if(firstInvalid){
    firstInvalid.reportValidity();
    return false;
  }
  normalizeMoneyInputs(form);
  return true;
}

window.formatMoneyInput=formatMoneyInput;
window.initMoneyInputs=initMoneyInputs;
window.normalizeMoneyInputs=normalizeMoneyInputs;
window.prepareMoneyForm=prepareMoneyForm;
window.parseMoneyNumber=function(value){
  return Number(String(value==null?'':value).replace(/,/g,''));
};

function initMoneyFormatter(){
  initMoneyInputs(document);
  document.addEventListener('input',function(event){
    if(isMoneyInput(event.target)){
      formatMoneyInput(event.target);
      validateMoneyInput(event.target);
    }
  });
  document.addEventListener('submit',function(event){
    if(!prepareMoneyForm(event.target)){
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  },true);
  document.addEventListener('reset',function(event){
    setTimeout(function(){initMoneyInputs(event.target);},0);
  },true);
  if(window.MutationObserver){
    new MutationObserver(function(records){
      records.forEach(function(record){
        record.addedNodes.forEach(function(node){
          if(node.nodeType===1)initMoneyInputs(node);
        });
      });
    }).observe(document.body,{childList:true,subtree:true});
  }
}

/* ── Flatpickr ── */
function initDates(){
  if(!window.flatpickr)return;
  document.querySelectorAll('input[type=date]').forEach(function(el){
    flatpickr(el,{dateFormat:'Y-m-d',allowInput:true,disableMobile:false});
  });
}

/* ── Job card: fee summary ── */
function syncFloatingSummary(label,total){
  var fse=document.getElementById('floatSumCount'),fst=document.getElementById('floatSumTotal'),fsg=document.getElementById('floatSumGrand');
  if(fse)fse.textContent=label;
  if(fst)fst.textContent='UGX '+total.toLocaleString();
  if(fsg)fsg.textContent='UGX '+total.toLocaleString();
}

function recalcTotal(){
  var total=0,count=0;
  document.querySelectorAll('.li-row').forEach(function(row){
    var del=row.querySelector('input[type=checkbox][name$="-DELETE"]');
    if(del&&del.checked)return;
    var v=window.parseMoneyNumber(row.querySelector('.li-price')?.value||0)||0;
    if(v>0){total+=v;count++;}
  });
  var label = count === 1 ? ' service' : ' services';
  var se=document.getElementById('sumCount'),st=document.getElementById('sumTotal'),sg=document.getElementById('sumGrand');
  if(se)se.textContent=label === ' service' ? '0 services' : count+label;
  if(st)st.textContent='UGX '+total.toLocaleString();
  if(sg)sg.textContent='UGX '+total.toLocaleString();
  syncFloatingSummary(count+label,total);
}
window.recalcTotal=recalcTotal;

/* ── Add line item ── */
function initAddLine(){
  var btn=document.getElementById('addLine');
  if(!btn)return;
  btn.addEventListener('click',function(){
    var container=document.getElementById('lineItems');
    var totalEl=document.getElementById('id_form-TOTAL_FORMS');
    if(!container||!totalEl)return;
    var total=parseInt(totalEl.value)||0;
    var tpl=document.querySelector('.li-row');
    if(!tpl)return;
    var clone=tpl.cloneNode(true);
    clone.querySelectorAll('input[type=text],input[type=number]').forEach(function(el){el.value='';});
    clone.querySelectorAll('select').forEach(function(el){el.selectedIndex=0;});
    clone.querySelectorAll('input[type=checkbox]').forEach(function(el){el.checked=false;});
    clone.querySelectorAll('[name]').forEach(function(el){
      el.name=el.name.replace(/-\d+-/,'-'+total+'-');
      if(el.id)el.id=el.id.replace(/_\d+_/,'_'+total+'_');
    });
    clone.querySelectorAll('.select2-container').forEach(function(el){el.remove();});
    clone.querySelectorAll('select').forEach(function(el){
      el.removeAttribute('data-select2-id');
      el.classList.remove('select2-hidden-accessible');
    });
    clone.querySelector('.li-num')&&(clone.querySelector('.li-num').textContent='Service '+(total+1));
    container.appendChild(clone);
    totalEl.value=total+1;
    // re-init select2 on new row
    if(window.jQuery&&jQuery.fn.select2){
      jQuery(clone).find('.s2').select2({theme:'bootstrap-5',allowClear:false});
      jQuery(clone).find('.s2-svc').select2({theme:'bootstrap-5',allowClear:false,
        placeholder:'Search services…'});
    }
    // auto-fill period
    var m=document.querySelector('[name=period_month]');
    var y=document.querySelector('[name=period_year]');
    var mOpt=m&&m.options[m.selectedIndex];
    if(mOpt&&mOpt.value&&y&&y.value){
      var pl=clone.querySelector('.li-period');
      if(pl&&!pl.value)pl.value=mOpt.text+' '+y.value;
    }
  });
}

/* ── Auto period label ── */
function initPeriodAuto(){
  document.querySelectorAll('[name=period_month],[name=period_year]').forEach(function(el){
    el.addEventListener('change',function(){
      var m=document.querySelector('[name=period_month]');
      var y=document.querySelector('[name=period_year]');
      if(!m||!y)return;
      var mOpt=m.options[m.selectedIndex];
      if(mOpt&&mOpt.value&&y.value){
        document.querySelectorAll('.li-period').forEach(function(p){
          if(!p.value)p.value=mOpt.text+' '+y.value;
        });
      }
    });
  });
}

/* ── Auto-dismiss alerts ── */
function initAlerts(){
  document.querySelectorAll('.auto-dismiss').forEach(function(el){
    setTimeout(function(){
      el.style.transition='opacity .4s';el.style.opacity='0';
      setTimeout(function(){el.remove();},400);
    },4500);
  });
}

/* ── Confirm actions ── */
function initConfirm(){
  document.querySelectorAll('[data-confirm]').forEach(function(el){
    el.addEventListener('click',function(e){if(!confirm(this.dataset.confirm))e.preventDefault();});
  });
}

/* ── Password toggle ── */
function initPwToggle(){
  document.querySelectorAll('.pw-toggle').forEach(function(btn){
    btn.addEventListener('click',function(){
      var t=document.getElementById(this.dataset.target);
      if(!t)return;
      t.type=t.type==='password'?'text':'password';
      this.innerHTML=t.type==='password'?'<i class="fas fa-eye"></i>':'<i class="fas fa-eye-slash"></i>';
    });
  });
}

/* ── Copy to clipboard ── */
function initCopy(){
  document.querySelectorAll('.copy-btn').forEach(function(btn){
    btn.addEventListener('click',function(){
      var text=this.dataset.copy||document.getElementById(this.dataset.copyFrom)?.textContent||'';
      navigator.clipboard.writeText(text.trim()).then(function(){
        btn.innerHTML='<i class="fas fa-check"></i> Copied!';
        setTimeout(function(){btn.innerHTML='<i class="fas fa-copy"></i> Copy';},1800);
      });
    });
  });
}

/* ── Credential reveal modal ── */
function initCredModal(){
  /* handled inline in credential_list.html */
}

/* ── Client batch import preview ── */
function initImportPreview(){
  var fileInput=document.getElementById('importFile');
  if(!fileInput)return;
  fileInput.addEventListener('change',function(){
    var file=this.files[0];if(!file)return;
    var reader=new FileReader();
    reader.onload=function(e){
      var lines=e.target.result.split('\n').filter(function(l){return l.trim();});
      var preview=document.getElementById('importPreview');
      if(!preview)return;
      var html='<div style="font-size:.78rem;color:#555;margin-bottom:.4rem">Preview: <strong>'+
        (lines.length-1)+'</strong> clients to import</div>';
      html+='<div class="tbl-wrap"><table class="tbl"><thead><tr>';
      var headers=lines[0].split(',');
      headers.forEach(function(h){html+='<th>'+h.trim()+'</th>';});
      html+='</tr></thead><tbody>';
      lines.slice(1,6).forEach(function(line){
        html+='<tr>';
        line.split(',').forEach(function(cell){html+='<td>'+cell.trim()+'</td>';});
        html+='</tr>';
      });
      if(lines.length>6)html+='<tr><td colspan="'+headers.length+'" style="text-align:center;color:#aaa">... and '+(lines.length-6)+' more</td></tr>';
      html+='</tbody></table></div>';
      preview.innerHTML=html;
    };
    reader.readAsText(file);
  });
}

/* ── Mobile table labels ── */
function initTableLabels(){
  document.querySelectorAll('table.tbl, table.table, table.table-taxman').forEach(function(tbl){
    var hdrs=Array.from(tbl.querySelectorAll('thead th')).map(function(th){return th.textContent.trim();});
    tbl.querySelectorAll('tbody td').forEach(function(td,i){
      if(hdrs[i%hdrs.length])td.setAttribute('data-lbl',hdrs[i%hdrs.length]);
    });
  });
}

/* ── Keyboard Shortcuts ── */
function initKeyboardShortcuts(){
  /* Build cheatsheet DOM once */
  var sheet = null;

  function getSheet(){
    if(sheet) return sheet;
    sheet = document.createElement('div');
    sheet.id = 'kb-sheet';
    sheet.innerHTML =
      '<div id="kb-inner">'+
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.9rem">'+
      '<strong style="font-size:.95rem;color:var(--blue)"><i class="fas fa-keyboard" style="color:var(--gold);margin-right:.4rem"></i>Keyboard Shortcuts</strong>'+
      '<button id="kb-close" style="background:none;border:none;font-size:1.2rem;cursor:pointer;color:#888;line-height:1">&times;</button>'+
      '</div>'+
      '<div class="kb-grid">'+
      r('Alt+D','Dashboard')+r('Alt+C','Clients')+r('Alt+J','Job Cards')+
      r('Alt+B','Billing')+r('Alt+E','Expenses')+r('Alt+K','Compliance')+
      r('Alt+R','Reports')+r('Alt+S','Settings')+
      r('Alt+Shift+C','New Client')+r('Alt+Shift+J','New Job Card')+
      r('Alt+Shift+I','New Invoice')+r('Alt+Shift+E','New Expense')+
      r('Alt+\\','Toggle Sidebar')+r('Alt+/','This help')+r('Esc','Close')+
      '</div></div>';
    document.body.appendChild(sheet);
    document.getElementById('kb-close').onclick = hide;
    sheet.addEventListener('click', function(e){ if(e.target===sheet) hide(); });
    return sheet;
  }

  function r(k,l){
    return '<div class="kb-row"><kbd>'+k+'</kbd><span>'+l+'</span></div>';
  }

  function show(){ getSheet().classList.add('open'); }
  function hide(){ if(sheet) sheet.classList.remove('open'); }

  /* Expose show so topbar button can call it */
  window.txShowShortcuts = show;

  var NAV = {d:'/dashboard/',c:'/clients/',j:'/jobs/',b:'/billing/',e:'/expenses/',k:'/compliance/',r:'/documents/price-list/',s:'/staff/settings/'};
  var NEW = {c:'/clients/new/',j:'/jobs/new/',i:'/billing/new/',e:'/expenses/new/'};

  document.addEventListener('keydown',function(e){
    if(!e.altKey && e.key!=='Escape' && e.key!=='?') return;

    var key=e.key.toLowerCase();

    /* Esc — close sheet */
    if(e.key==='Escape'){ hide(); return; }

    /* Alt+/ — show help */
    if(e.altKey && e.key==='/'){
      e.preventDefault(); show(); return;
    }

    /* Alt+\ — toggle sidebar */
    if(e.altKey && (e.key==='\\'||e.key==='|')){
      e.preventDefault();
      var tb=document.getElementById('sidebarToggle');
      if(tb) tb.click();
      return;
    }

    /* Alt+letter — navigate */
    if(e.altKey && !e.shiftKey && NAV[key]){
      /* skip browser defaults only for our keys */
      e.preventDefault();
      window.location.href=NAV[key];
      return;
    }

    /* Alt+Shift+letter — create new */
    if(e.altKey && e.shiftKey && NEW[key]){
      e.preventDefault();
      window.location.href=NEW[key];
      return;
    }
  });
}

/* ── Init all ── */
document.addEventListener('DOMContentLoaded',function(){
  initMoneyFormatter();
  initSelect2();
  initDates();
  initAlerts();
  initConfirm();
  initPwToggle();
  initCopy();
  initCredModal();
  initAddLine();
  initPeriodAuto();
  initImportPreview();
  initTableLabels();
  initKeyboardShortcuts();
  recalcTotal();
});

})();
