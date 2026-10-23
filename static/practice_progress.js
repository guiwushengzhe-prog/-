/* 每首曲目的练习位置独立保存；恢复时始终保持暂停。 */
(() => {
  'use strict';
  const storageKey='piano-light-practice-progress-v1';
  class PracticeProgress {
    constructor(storage){this.storage=storage;this.identities=new WeakMap();}
    key(raw){
      const project=raw?.key_adaptation?.original_project||raw;
      if(!project?.notes?.length||project.source?.kind==='demo'||/demo|示例|built-in/i.test(project.transcription?.engine||''))return null;
      if(this.identities.has(project))return this.identities.get(project);
      const notes=project.source_notes||project.notes;
      let hash=2166136261;
      const text=JSON.stringify([project.title,notes.map(note=>[note.pitch,note.start,note.end])]);
      for(let i=0;i<text.length;i++)hash=Math.imul(hash^text.charCodeAt(i),16777619);
      const key=`${notes.length}:${(hash>>>0).toString(16)}`;this.identities.set(project,key);return key;
    }
    read(){
      try{
        const saved=JSON.parse(this.storage.getItem(storageKey)||'{}');
        return saved&&typeof saved==='object'&&saved.entries&&typeof saved.entries==='object'?saved:{entries:{}};
      }catch(_){return {entries:{}};}
    }
    get(raw){const key=this.key(raw);return key?this.read().entries[key]||null:null;}
    last(){return this.read().last||null;}
    save(raw,position){
      const key=this.key(raw);if(!key)return;
      const saved=this.read();
      saved.entries[key]={...position,updatedAt:Date.now()};saved.last=key;
      const keys=Object.keys(saved.entries).sort((a,b)=>saved.entries[b].updatedAt-saved.entries[a].updatedAt);
      for(const old of keys.slice(40))delete saved.entries[old];
      try{this.storage.setItem(storageKey,JSON.stringify(saved));}catch(_){}
    }
  }
  window.PianoProgressStore=PracticeProgress;
})();
