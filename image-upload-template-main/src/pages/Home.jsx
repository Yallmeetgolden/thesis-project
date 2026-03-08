import { useState, useCallback, useRef } from 'react';
import { FormikProvider, useFormik } from 'formik';
import { useDropzone } from 'react-dropzone';
import { Icon } from '@iconify/react';
import JSZip from 'jszip';
import { _uploadImage, useImageUpload } from '../api/image';
import '../App.css';
import { useAuth } from '../context/AuthContext';

async function createBitmap(file) {
  try { return await createImageBitmap(file); }
  catch (e) {
    return new Promise((resolve, reject) => {
      const img = new Image(); img.onload = () => resolve(img); img.onerror = reject; img.src = URL.createObjectURL(file);
    });
  }
}

function drawToCanvasBitmap(bitmap, w, h) {
  const canvas = document.createElement('canvas'); canvas.width = w; canvas.height = h; const ctx = canvas.getContext('2d'); ctx.drawImage(bitmap,0,0,w,h); return ctx.getImageData(0,0,w,h);
}

function grayscalePixels(imageData) {
  const {data, width, height} = imageData; const g = new Float32Array(width*height);
  for (let i=0;i<width*height;i++){ const r=data[i*4], gg=data[i*4+1], b=data[i*4+2]; g[i]=0.2126*r+0.7152*gg+0.0722*b; }
  return {g,width,height};
}

function laplacianVariance(imageData){ const {g,width,height}=grayscalePixels(imageData); const lap=new Float32Array(width*height); const kernel=[0,1,0,1,-4,1,0,1,0]; for(let y=1;y<height-1;y++){ for(let x=1;x<width-1;x++){ let s=0,k=0; for(let ky=-1;ky<=1;ky++){ for(let kx=-1;kx<=1;kx++){ const px=g[(y+ky)*width+(x+kx)]; s+=px*kernel[k++]; } } lap[y*width+x]=s; } } let mean=0,cnt=0; for(let i=0;i<lap.length;i++){ mean+=lap[i]; cnt++; } mean/=cnt; let varSum=0; for(let i=0;i<lap.length;i++){ const d=lap[i]-mean; varSum+=d*d; } return varSum/cnt; }

function averageLuminance(imageData){ const {g}=grayscalePixels(imageData); let s=0; for(let i=0;i<g.length;i++) s+=g[i]; return s/g.length; }

function computeAHashFromImageData(imageData){ const {g}=grayscalePixels(imageData); let sum=0; for(let i=0;i<g.length;i++) sum+=g[i]; const mean=sum/g.length; let hash=''; for(let i=0;i<g.length;i++) hash+=(g[i]>mean)?'1':'0'; return hash; }

function hammingDistance(a,b){ let d=0; for(let i=0;i<a.length;i++) if(a[i]!==b[i]) d++; return d; }

export default function Home(){
  const { imageUploadMutation } = useImageUpload();
  const [analysis, setAnalysis] = useState([]);
  const [running, setRunning] = useState(false);
  const { logout, currentUser } = useAuth();
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  const handleToggleUserMenu = () => setUserMenuOpen(v=>!v);
  const handleSignOut = async () => { setUserMenuOpen(false); await logout(); };

  const formik = useFormik({ initialValues: { files: [] }, onSubmit: (data)=>{ const formData=new FormData(); data?.files.forEach((file)=>formData.append('files',file)); imageUploadMutation.mutate(formData); } });
  const { values, setFieldValue, handleSubmit } = formik;

  const onDrop = useCallback((acceptedFiles)=>{ setFieldValue('files', acceptedFiles.map(f=>Object.assign(f))); }, [setFieldValue]);
  const { getRootProps, getInputProps } = useDropzone({ onDrop, multiple: true });
  const dirInputRef = useRef(null);
  const handleDirChange = (e) => {
    const files = Array.from(e.target.files || []);
    setFieldValue('files', files.map(f=>Object.assign(f)));
  };

  const handleRemoveFile = (file) => { const uploadedFiles = values?.files || []; const filtered = uploadedFiles.filter((i)=>i.name!==file.name); setFieldValue('files',[...filtered]); setAnalysis(prev=>prev.filter(a=>a.file.name!==file.name)); };
  const handleRemoveAllFiles = () => { setFieldValue('files',[]); setAnalysis([]); };

  async function analyze(){
    const files = values.files || [];
    if(!files.length){ alert('No files'); return; }
    setRunning(true);
    const items=[];
    for(const f of files){ if(!f.type.startsWith('image')) continue; try{ const bmp = await createBitmap(f); const small = drawToCanvasBitmap(bmp,128,128); const luminance = averageLuminance(small); const lapVar = laplacianVariance(small); const hash8 = computeAHashFromImageData(drawToCanvasBitmap(bmp,8,8)); items.push({file:f,luminance,lapVar,aHash:hash8,selected:false}); }catch(e){ console.warn('fail', f.name, e); } }

    const duplicates = new Map();
    for(let i=0;i<items.length;i++){ for(let j=i+1;j<items.length;j++){ const d=hammingDistance(items[i].aHash, items[j].aHash); if(d<=8) duplicates.set(items[j].file.name, items[i].file.name); } }

    const blurThreshold = parseInt(document.getElementById('blurThreshold')?.value || '1500',10);
    const darkThreshold = parseInt(document.getElementById('darkThreshold')?.value || '60',10);
    const brightThreshold = parseInt(document.getElementById('brightThreshold')?.value || '200',10);
    const detectBlur = document.getElementById('detectBlur')?.checked;
    const detectLight = document.getElementById('detectLight')?.checked;
    const detectDuplicates = document.getElementById('detectDuplicates')?.checked;

    for(const it of items){ const isDup = duplicates.has(it.file.name); const isBlurry = it.lapVar < blurThreshold; const badLight = (it.luminance < darkThreshold) || (it.luminance > brightThreshold); let score=0; if(detectBlur && !isBlurry) score++; if(detectLight && !badLight) score++; if(detectDuplicates && !isDup) score++; it.score=score; it.isDuplicate=isDup; it.isBlurry=isBlurry; it.badLight=badLight; }

    items.sort((a,b)=>b.score-a.score);
    setAnalysis(items);
    setRunning(false);
  }

  const selectTop = ()=>{ const topN = Math.max(1, parseInt(document.getElementById('topN')?.value || '10',10)); setAnalysis(prev=>prev.map((it,idx)=>({...it, selected: idx<topN}))); };

  const exportSelected = async ()=>{ const selected = analysis.filter(a=>a.selected); if(!selected.length){ alert('No selected files'); return; } const zip = new JSZip(); for(const it of selected){ const buf = await it.file.arrayBuffer(); zip.file(it.file.name, buf); } const blob = await zip.generateAsync({type:'blob'}); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href=url; a.download='selected_images.zip'; document.body.appendChild(a); a.click(); a.remove(); };

  const renderPreview = (file)=> file.type.startsWith('image') ? <img className="h-10 w-10" alt={file.name} src={URL.createObjectURL(file)} /> : <Icon icon="tabler:file-description" className="w-8" />;

  return (
    <div className="app-root">
      <header className="app-header">
        <div className="header-left" />
        <div className="header-right">
          <div className="user-menu">
            <button className="user-button" onClick={handleToggleUserMenu} aria-expanded={userMenuOpen}>
              <Icon icon="mdi:account-circle" className="profile-icon" />
              <span className="caret">▾</span>
            </button>
            {userMenuOpen && (
              <div className="user-dropdown">
                <div className="user-dropdown-item">Signed in as <strong>{currentUser?.email || currentUser?.displayName}</strong></div>
                <button className="user-dropdown-item user-logout" onClick={handleSignOut}>Sign out</button>
              </div>
            )}
          </div>
        </div>
      </header>
      <div className="app-container">
        <h1 className="title">Ai based photo selector & analyzer</h1>
        <FormikProvider value={formik}>
          <form onSubmit={handleSubmit} className="app-form">
            <div {...getRootProps({ className: 'dropzone' })} className="dropzone">
              <input {...getInputProps({ multiple: true })} />
              <input ref={dirInputRef} type="file" style={{display:'none'}} webkitdirectory="true" directory="" multiple onChange={handleDirChange} />
              <div className="dropzone-inner">
                <Icon icon="lucide:upload" className="upload-icon" />
                <p className="upload-text"><span className="upload-text" style={{color:'#eb2553'}}>Click to upload folder(s)</span> or drag and drop</p>
                <button type="button" onClick={()=>dirInputRef.current && dirInputRef.current.click()} className="select-folder-btn">Select folder</button>
                <p className="muted">You can remove files after analysis or export selected.</p>
              </div>
            </div>

            {values?.files.length ? (
              <>
                <div className="file-list">
                  {analysis.length ? analysis.map((it, idx) => (
                    <div key={it.file.name} className="file-item">
                      <div className="file-left">
                        <div className="file-preview">{renderPreview(it.file)}</div>
                        <div>
                          <div className="file-name">{it.file.name}</div>
                          <div className="file-meta">Score: {it.score} {it.isDuplicate? ' · Duplicate':''} {it.isBlurry? ' · Blurry':''} {it.badLight? ' · Bad Light':''}</div>
                        </div>
                      </div>
                      <div className="file-actions">
                        <input type="checkbox" checked={!!it.selected} onChange={(e)=>{ const newA = analysis.map(a=> a.file.name===it.file.name?{...a,selected:e.target.checked}:a); setAnalysis(newA); }} />
                        <button type="button" onClick={()=>handleRemoveFile(it.file)} className="small-border"><Icon icon="tabler:trash" /></button>
                      </div>
                    </div>
                  )) : values.files.map((file) => (
                    <div key={file.name} className="file-item">
                      <div className="file-left">
                        <div className="file-preview">{renderPreview(file)}</div>
                        <div>
                          <div className="file-name">{file.name}</div>
                          <div className="file-meta">{Math.round(file.size/100)/10>1000? `${(Math.round(file.size/100)/10000).toFixed(1)} mb`:`${(Math.round(file.size/100)/10).toFixed(1)} kb`}</div>
                        </div>
                      </div>
                      <div className="file-actions">
                        <button type="button" onClick={()=>handleRemoveFile(file)} className="small-border"><Icon icon="tabler:trash" /></button>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 flex justify-end gap-2">
                  <button type="button" className="border rounded-full py-2 px-3 text-sm" onClick={handleRemoveAllFiles}>Remove All</button>
                </div>
              </>
            ) : null}

            <div className="controls">
              <label>Top results: <input id="topN" defaultValue={10} type="number" min={1} style={{width:72,marginLeft:6}}/></label>
              <button type="button" onClick={selectTop} className="btn btn-black">Select Top</button>
              <button type="button" onClick={exportSelected} className="btn btn-black">Export Selected (ZIP)</button>
              <label><input id="detectDuplicates" defaultChecked type="checkbox" style={{marginLeft:8}}/> Detect duplicates</label>
              <label><input id="detectBlur" defaultChecked type="checkbox" style={{marginLeft:8}}/> Detect blurry</label>
              <label><input id="detectLight" defaultChecked type="checkbox" style={{marginLeft:8}}/> Detect bad lighting</label>
              <div className="controls-center">
                <button type="button" onClick={analyze} className="btn btn-blue">Run Analysis</button>
              </div>
            </div>

            <div className="submit-area">
              <button type="submit" className="submit-btn">Upload</button>
            </div>
          </form>
        </FormikProvider>
      </div>
    </div>
  );
}
