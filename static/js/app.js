const chat = document.getElementById('chat');
const form = document.getElementById('chatForm');
const question = document.getElementById('question');
const trace = document.getElementById('trace');
const sourceUsed = document.getElementById('sourceUsed');
const flightSearchForm = document.getElementById('flightSearchForm');
const originCode = document.getElementById('originCode');
const destinationCode = document.getElementById('destinationCode');
const departureDate = document.getElementById('departureDate');
const returnDate = document.getElementById('returnDate');
const appConfig = window.APP_CONFIG || {};

function chatApiUrl(){
  if(!appConfig.staticPages) return '/api/chat';
  const apiBaseUrl=(appConfig.apiBaseUrl||'').replace(/\/+$/,'');
  return apiBaseUrl?`${apiBaseUrl}/api/chat`:'';
}

function escapeHtml(s=''){return s.replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function formatText(s=''){return escapeHtml(s).replace(/\n/g,'<br>');}
function sourceLabel(source=''){
  if(source==='kb') return 'Pages de référence';
  if(source==='official_page_link') return 'Lien de page officielle';
  if(source==='live_flight_status') return 'Page officielle des vols en cours';
  if(source.startsWith('tunisair_booking')) return 'Réservation de vol';
  return source;
}
function addMessage(role, text, source='', citations=[]){
  const wrap=document.createElement('div'); wrap.className=`message ${role}`;
  const citeHtml=citations.length?`<div class="citations"><strong>Sources officielles</strong>${citations.map(c=>c.url?`<a href="${escapeHtml(c.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(c.title)}</a>`:escapeHtml(c.title)).join('')}</div>`:'';
  wrap.innerHTML=`<div class="avatar" aria-hidden="true">${role==='assistant'?'F':''}</div><div class="bubble">${formatText(text)}${source?`<div class="answer-source">Source : ${escapeHtml(sourceLabel(source))}</div>`:''}${citeHtml}</div>`;
  chat.appendChild(wrap); chat.scrollTop=chat.scrollHeight;
}
function renderTrace(items=[]){trace.innerHTML=items.length?items.map(x=>`<div class="trace-item">${escapeHtml(x)}</div>`).join(''):'<div class="empty">Aucune demande pour le moment.</div>';}
async function askAgent(q){
  addMessage('user',q); question.value=''; renderTrace(['Traitement de votre demande...']); sourceUsed.textContent='En cours';
  const btn=form.querySelector('button'); btn.disabled=true;
  try{
    const endpoint=chatApiUrl();
    if(!endpoint) throw new Error('Le service de chat n’est pas encore configuré. Réessayez plus tard.');
    const res=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})});
    const data=await res.json(); if(!res.ok) throw new Error(data.detail||'La demande a échoué.');
    addMessage('assistant',data.answer,data.source_used,data.citations||[]); renderTrace(data.trace||[]); sourceUsed.textContent=sourceLabel(data.source_used);
  }catch(e){addMessage('assistant',`Désolé, une erreur est survenue : ${e.message}`); renderTrace(['La demande a échoué']); sourceUsed.textContent='Erreur';}
  finally{btn.disabled=false;}
}
form.addEventListener('submit',e=>{e.preventDefault(); const q=question.value.trim(); if(q) askAgent(q);});
document.querySelectorAll('.example').forEach(b=>b.addEventListener('click',()=>askAgent(b.textContent.trim())));

function localDateString(date){
  const year=date.getFullYear();
  const month=String(date.getMonth()+1).padStart(2,'0');
  const day=String(date.getDate()).padStart(2,'0');
  return `${year}-${month}-${day}`;
}
function setReturnDateMinimum(){
  returnDate.min=departureDate.value||departureDate.min;
  if(returnDate.value&&returnDate.value<returnDate.min) returnDate.value=returnDate.min;
}
const today=new Date();
const defaultDeparture=new Date(today);
defaultDeparture.setDate(today.getDate()+7);
const defaultReturn=new Date(today);
defaultReturn.setDate(today.getDate()+14);
departureDate.min=localDateString(today);
departureDate.value=localDateString(defaultDeparture);
returnDate.value=localDateString(defaultReturn);
setReturnDateMinimum();
departureDate.addEventListener('change',setReturnDateMinimum);
document.getElementById('swapRoute').addEventListener('click',()=>{
  const selectedOrigin=originCode.value;
  originCode.value=destinationCode.value;
  destinationCode.value=selectedOrigin;
  destinationCode.setCustomValidity('');
});
originCode.addEventListener('change',()=>destinationCode.setCustomValidity(''));
destinationCode.addEventListener('change',()=>destinationCode.setCustomValidity(''));
flightSearchForm.addEventListener('submit',event=>{
  event.preventDefault();
  setReturnDateMinimum();
  if(originCode.value===destinationCode.value){
    destinationCode.setCustomValidity('Choisissez une destination différente du départ.');
    destinationCode.reportValidity();
    return;
  }
  destinationCode.setCustomValidity('');
  const prompt=`Prépare une recherche aller-retour. Code de départ : ${originCode.value}. Code de destination : ${destinationCode.value}. Date aller : ${departureDate.value}. Date retour : ${returnDate.value}.`;
  askAgent(prompt);
  document.getElementById('assistant').scrollIntoView({behavior:'smooth',block:'start'});
});
