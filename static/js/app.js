/* Taxman256 — Main JS */
(function(){
'use strict';

/* ── Sidebar ── */
/* Handled by inline <script> in base.html */

/* ── Select2 init ── */
function initSelect2(){
  if(!window.jQuery||!jQuery.fn.select2)return;
  jQuery('.s2, .select2').filter(function(){
    return !jQuery(this).hasClass('select2-hidden-accessible');
  }).select2({theme:'bootstrap-5',allowClear:false,
    placeholder:function(){return jQuery(this).data('ph')||'Search or select…';}});
  // service select: autofill price
  jQuery(document).on('select2:select','.s2-svc',function(e){
    var price=jQuery(e.params.data.element).data('price')||'',
        vat=jQuery(e.params.data.element).data('vat')||false,
        row=jQuery(this).closest('.li-row');
    if(price){
      row.find('.li-default').val(price);
      if(!row.find('.li-price').val())row.find('.li-price').val(price);
      row.find('.li-vat-badge').toggle(!!vat);
    }
    recalcTotal();
  });
  jQuery(document).on('input','.li-price',recalcTotal);
  jQuery(document).on('change','.li-delete',recalcTotal);
}

/* ── Flatpickr ── */
function initDates(){
  if(!window.flatpickr)return;
  document.querySelectorAll('input[type=date]').forEach(function(el){
    flatpickr(el,{dateFormat:'Y-m-d',allowInput:true,disableMobile:false});
  });
}

/* ── Job card: fee summary ── */
function recalcTotal(){
  var total=0,count=0;
  document.querySelectorAll('.li-row').forEach(function(row){
    var del=row.querySelector('.li-delete');
    if(del&&del.checked)return;
    var v=parseFloat(row.querySelector('.li-price')?.value||0)||0;
    if(v>0){total+=v;count++;}
  });
  var se=document.getElementById('sumCount'),st=document.getElementById('sumTotal');
  if(se)se.textContent=count+(count===1?' service':' services');
  if(st)st.textContent='UGX '+total.toLocaleString();
}
window.recalcTotal=recalcTotal;

/* ── Add line item ── */
function initAddLine(){
  var btn=document.getElementById('addLine');
  if(!btn)return;
  btn.addEventListener('click',function(){
    var container=document.getElementById('lineItems');
    var total=parseInt(document.getElementById('id_form-TOTAL_FORMS').value)||0;
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
    document.getElementById('id_form-TOTAL_FORMS').value=total+1;
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
  var modal=document.getElementById('credModal');
  if(!modal)return;
  var csrf=document.querySelector('[name=csrfmiddlewaretoken]');
  document.querySelectorAll('.reveal-btn').forEach(function(btn){
    btn.addEventListener('click',function(){
      var pk=this.dataset.pk;
      fetch('/credentials/'+pk+'/reveal/',{
        headers:{'X-CSRFToken':csrf?csrf.value:''}
      }).then(function(r){return r.json();}).then(function(d){
        if(d.error){alert('Access denied: '+d.error);return;}
        document.getElementById('cred-uname').textContent=d.username||'(not set)';
        document.getElementById('cred-pw').textContent=d.password||'(not set)';
        document.getElementById('cred-notes').textContent=d.notes||'';
        document.getElementById('cred-copy-u').dataset.copy=d.username||'';
        document.getElementById('cred-copy-p').dataset.copy=d.password||'';
        modal.classList.add('open');
      });
    });
  });
  modal.addEventListener('click',function(e){if(e.target===modal)modal.classList.remove('open');});
  document.querySelectorAll('.modal-close').forEach(function(b){
    b.addEventListener('click',function(){modal.classList.remove('open');});
  });
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

/* ── Init all ── */
document.addEventListener('DOMContentLoaded',function(){
  initSelect2();
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
  recalcTotal();
});

})();
