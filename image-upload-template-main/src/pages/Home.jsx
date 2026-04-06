import { useState, useRef, useMemo } from 'react';
import { FormikProvider, useFormik } from 'formik';
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
  const [uploadCount, setUploadCount] = useState(0);
  const [uploadArchiveName, setUploadArchiveName] = useState('');
  const [uploadArchiveSize, setUploadArchiveSize] = useState(0);
  const [selectedZipFile, setSelectedZipFile] = useState(null);
  const [selectedZipImageCount, setSelectedZipImageCount] = useState(0);
  const [inspectingZip, setInspectingZip] = useState(false);
  const [uploadingZip, setUploadingZip] = useState(false);
  const [processingZip, setProcessingZip] = useState(false);
  const [analysisDone, setAnalysisDone] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [processingProgress, setProcessingProgress] = useState(0);
  const [processedEntries, setProcessedEntries] = useState(0);
  const [totalEntries, setTotalEntries] = useState(0);
  const [analysisSessionId, setAnalysisSessionId] = useState('');
  const [analyzingBlur, setAnalyzingBlur] = useState(false);
  const [blurResult, setBlurResult] = useState(null);
  const [detectBlurEnabled, setDetectBlurEnabled] = useState(false);
  const [showBlurThresholdPopup, setShowBlurThresholdPopup] = useState(false);
  const [blurQualityMode, setBlurQualityMode] = useState('acceptable');
  const [pendingBlurQualityMode, setPendingBlurQualityMode] = useState('acceptable');

  const qualityModeLabels = {
    very_blurry: 'Very blurry',
    slightly_blurry: 'Slightly blurry',
    acceptable: 'Acceptable',
    very_sharp: 'Very sharp'
  };

  const handleToggleUserMenu = () => setUserMenuOpen(v=>!v);
  const handleSignOut = async () => { setUserMenuOpen(false); await logout(); };

  const formik = useFormik({ initialValues: { files: [] }, onSubmit: (data)=>{ const formData=new FormData(); data?.files.forEach((file)=>formData.append('files',file)); imageUploadMutation.mutate(formData); } });
  const { values, setFieldValue, handleSubmit } = formik;

  const zipInputRef = useRef(null);

  const uploadArchiveWithProgress = (formData, token, onProgress) => {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', 'http://127.0.0.1:8000/server/api/upload.php');
      xhr.setRequestHeader('Authorization', 'Bearer ' + token);

      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) return;
        const percent = Math.min(100, Math.round((event.loaded / event.total) * 100));
        onProgress(percent);
      };

      xhr.onload = () => {
        const raw = xhr.responseText || '';
        let data = null;

        try {
          data = raw ? JSON.parse(raw) : null;
        } catch (err) {
          data = null;
        }

        if (xhr.status >= 200 && xhr.status < 300) {
          if (data && typeof data === 'object') {
            resolve(data);
            return;
          }

          const snippet = raw.trim().slice(0, 140);
          if (raw.includes('POST Content-Length') && raw.includes('exceeds the limit')) {
            reject(new Error('Upload is larger than PHP server limit (default ~8MB). Restart PHP with higher upload limits: php -d upload_max_filesize=1024M -d post_max_size=1024M -S 127.0.0.1:8000 router.php'));
            return;
          }
          reject(new Error(`Server returned non-JSON response (status ${xhr.status}). Check PHP server path/router. ${snippet ? 'Response: ' + snippet : ''}`));
          return;
        }

        if (data && data.error) {
          reject(new Error(data.error));
          return;
        }

        const snippet = raw.trim().slice(0, 140);
        if (raw.includes('POST Content-Length') && raw.includes('exceeds the limit')) {
          reject(new Error('Upload is larger than PHP server limit (default ~8MB). Restart PHP with higher upload limits: php -d upload_max_filesize=1024M -d post_max_size=1024M -S 127.0.0.1:8000 router.php'));
          return;
        }
        reject(new Error(`Upload failed (status ${xhr.status}). ${snippet ? 'Response: ' + snippet : ''}`));
      };

      xhr.onerror = () => reject(new Error('Network error while uploading ZIP'));
      xhr.send(formData);
    });
  };

  const processZipBatch = async (sessionId, token) => {
    const formData = new FormData();
    formData.append('sessionId', sessionId);
    formData.append('batchSize', '300');

    const res = await fetch('http://127.0.0.1:8000/server/api/process_zip.php', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
      body: formData
    });

    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data?.error || 'Processing failed');
    }
    return data;
  };

  const analyzeBlurBatch = async (sessionId, token, qualityMode = 'acceptable') => {
    const formData = new FormData();
    formData.append('sessionId', sessionId);
    formData.append('qualityMode', qualityMode);

    const res = await fetch('http://127.0.0.1:8000/server/api/analyze_blur.php', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
      body: formData
    });

    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data?.error || 'Blur analysis failed');
    }
    return data;
  };

  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const imageExt = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'nef', 'dng', 'cr2'];
  const maxZipBytes = 1024 * 1024 * 1024;

  const inspectZip = async (zipFile) => {
    const zip = await JSZip.loadAsync(zipFile);
    let count = 0;
    Object.values(zip.files).forEach((entry) => {
      if (entry.dir) return;
      const ext = (entry.name.split('.').pop() || '').toLowerCase();
      if (imageExt.includes(ext)) count++;
    });
    return count;
  };
  
  const handleZipChange = async (e) => {
    const zipFile = (e.target.files || [])[0];

    // Do not keep all files in React state to avoid UI lag with large folders
    setFieldValue('files', []);
    setAnalysis([]);
    setUploadCount(0);
    setUploadArchiveName('');
    setUploadArchiveSize(0);
    setSelectedZipFile(null);
    setSelectedZipImageCount(0);
    setUploadError('');
    setAnalysisDone(false);
    setUploadProgress(0);
    setProcessingProgress(0);
    setProcessedEntries(0);
    setTotalEntries(0);
    setAnalysisSessionId('');
    setAnalyzingBlur(false);
    setBlurResult(null);

    if (!zipFile) {
      setUploadError('No ZIP file selected.');
      return;
    }

    if (!zipFile.name.toLowerCase().endsWith('.zip')) {
      setUploadError('Please select a .zip file.');
      return;
    }

    if (zipFile.size > maxZipBytes) {
      setUploadError('ZIP is too large. Maximum allowed size is 1GB.');
      return;
    }

    try {
      setInspectingZip(true);
      const localCount = await inspectZip(zipFile);
      setSelectedZipFile(zipFile);
      setSelectedZipImageCount(localCount);
      setUploadArchiveName(zipFile.name);
      setUploadArchiveSize(zipFile.size);
    } catch (err) {
      console.warn('ZIP inspect error:', err);
      setUploadError('Could not read ZIP file. Please check the file and try again.');
    } finally {
      setInspectingZip(false);
      e.target.value = '';
    }
  };

  const runZipAnalysis = async () => {
    if (!selectedZipFile) {
      setUploadError('Please select a ZIP file first.');
      return;
    }

    setUploadError('');
    setAnalysisDone(false);
    setUploadProgress(0);
    setProcessingProgress(0);
    setProcessedEntries(0);
    setTotalEntries(0);
    setUploadCount(0);
    setBlurResult(null);
    setAnalyzingBlur(false);

    try {
      setUploadingZip(true);
      const token = localStorage.getItem('auth_token');
      const formData = new FormData();
      formData.append('archive', selectedZipFile);

      const data = await uploadArchiveWithProgress(formData, token, (percent) => {
        setUploadProgress(percent);
      });

      if (!data.success) {
        throw new Error(data?.error || 'Upload failed');
      }

      setUploadArchiveName(data.archiveName || selectedZipFile.name);
      setUploadArchiveSize(Number(data.archiveSize || selectedZipFile.size));
      setUploadProgress(100);

      const sessionId = data.sessionId;
      if (!sessionId) {
        throw new Error('Missing processing session');
      }
      setAnalysisSessionId(sessionId);

      setProcessingZip(true);
      while (true) {
        const progressData = await processZipBatch(sessionId, token);
        setProcessingProgress(Number(progressData.progress || 0));
        setProcessedEntries(Number(progressData.processedEntries || 0));
        setTotalEntries(Number(progressData.totalEntries || 0));
        setUploadCount(Number(progressData.imageCount || 0));

        if (progressData.status === 'done') {
          setProcessingProgress(100);
          break;
        }
        await wait(250);
      }

      if (detectBlurEnabled) {
        setAnalyzingBlur(true);
        const blurData = await analyzeBlurBatch(sessionId, token, blurQualityMode);
        setBlurResult(blurData);
      }

      setAnalysisDone(true);
    } catch (err) {
      console.warn('Backend upload error:', err);
      setUploadError(err?.message || 'Upload failed');
    } finally {
      setUploadingZip(false);
      setProcessingZip(false);
      setAnalyzingBlur(false);
    }
  };

  const handleAnalyzeZip = async () => {
    if (!selectedZipFile) {
      setUploadError('Please select a ZIP file first.');
      return;
    }

    await runZipAnalysis();
  };

  const handleConfirmBlurThreshold = async () => {
    setBlurQualityMode(pendingBlurQualityMode);
    setDetectBlurEnabled(true);
    setShowBlurThresholdPopup(false);
  };

  const handleCancelBlurThreshold = () => {
    setShowBlurThresholdPopup(false);
    setDetectBlurEnabled(false);
  };

  const handleDetectBlurChange = (checked) => {
    if (checked) {
      setPendingBlurQualityMode(blurQualityMode);
      setShowBlurThresholdPopup(true);
      return;
    }

    setDetectBlurEnabled(false);
  };

  const handleDropzoneClick = () => zipInputRef.current?.click();

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
  const selectedScoreByName = useMemo(() => {
    const map = new Map();
    if (Array.isArray(blurResult?.selectedFileScores)) {
      blurResult.selectedFileScores.forEach((item) => {
        if (item?.filename) map.set(item.filename, item);
      });
    }
    return map;
  }, [blurResult]);

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
            <div className="dropzone" onClick={handleDropzoneClick} style={{cursor: 'pointer'}}>
              <input ref={zipInputRef} type="file" style={{display:'none'}} accept=".zip,application/zip,application/x-zip-compressed" onChange={handleZipChange} />
              <div className="dropzone-inner">
                <Icon icon="lucide:upload" className="upload-icon" />
                <p className="upload-text"><span className="upload-text" style={{color:'#eb2553'}}>Click to upload ZIP</span> or drag and drop</p>
                <p className="muted">Select a .zip file that contains your images.</p>
              </div>
            </div>

            {(inspectingZip || selectedZipFile) && (
              <div style={{marginTop: '1rem', padding: '0.75rem', borderRadius: '0.375rem', backgroundColor: '#F8FAFC', border: '1px solid #CBD5E1'}}>
                {inspectingZip && <p style={{margin: 0, fontSize: '0.9rem', color: '#334155'}}><strong>Reading ZIP file...</strong></p>}
                {!inspectingZip && selectedZipFile && (
                  <>
                    <p style={{margin: 0, fontSize: '0.9rem', color: '#0F172A'}}><strong>ZIP ready:</strong> {selectedZipFile.name}</p>
                    <p style={{margin: '0.35rem 0 0', fontSize: '0.8rem', color: '#334155'}}>Estimated images in ZIP: <strong>{selectedZipImageCount}</strong></p>
                    <p style={{margin: '0.35rem 0 0', fontSize: '0.8rem', color: '#334155'}}>ZIP size: <strong>{(selectedZipFile.size / (1024 * 1024)).toFixed(2)} MB</strong></p>
                  </>
                )}
              </div>
            )}

            {(uploadingZip || processingZip || analyzingBlur || uploadError || analysisDone) && (
              <div style={{marginTop: '1rem', padding: '0.75rem', borderRadius: '0.375rem', backgroundColor: uploadError ? '#FEF2F2' : '#E0F2FE', border: uploadError ? '1px solid #EF4444' : '1px solid #0284C7'}}>
                {uploadingZip && <p style={{margin: 0, fontSize: '0.9rem', color: '#0C4A6E'}}><strong>Uploading ZIP...</strong></p>}
                {uploadingZip && <p style={{margin: '0.35rem 0 0', fontSize: '0.8rem', color: '#0C4A6E'}}>Upload: <strong>{uploadProgress}%</strong></p>}
                {processingZip && <p style={{margin: '0.35rem 0 0', fontSize: '0.9rem', color: '#0C4A6E'}}><strong>Processing ZIP on server...</strong></p>}
                {processingZip && <p style={{margin: '0.35rem 0 0', fontSize: '0.8rem', color: '#0C4A6E'}}>Processing: <strong>{processingProgress}%</strong> ({processedEntries}/{totalEntries} entries)</p>}
                {analyzingBlur && <p style={{margin: '0.35rem 0 0', fontSize: '0.9rem', color: '#0C4A6E'}}><strong>Analyzing blurry images...</strong></p>}
                {!uploadingZip && uploadError && <p style={{margin: 0, fontSize: '0.9rem', color: '#991B1B'}}><strong>Upload failed:</strong> {uploadError}</p>}
                {!uploadingZip && !processingZip && !analyzingBlur && analysisDone && uploadArchiveName && (
                  <>
                    <p style={{margin: 0, fontSize: '0.9rem', color: '#0C4A6E'}}><strong>{uploadCount} images</strong> found in ZIP and stored on server ✓</p>
                    <p style={{margin: '0.35rem 0 0', fontSize: '0.8rem', color: '#0C4A6E'}}>Archive: <strong>{uploadArchiveName}</strong></p>
                    <p style={{margin: '0.35rem 0 0', fontSize: '0.8rem', color: '#0C4A6E'}}>ZIP size: <strong>{(uploadArchiveSize / (1024 * 1024)).toFixed(2)} MB</strong></p>
                    {!!analysisSessionId && <p style={{margin: '0.35rem 0 0', fontSize: '0.8rem', color: '#0C4A6E'}}>Session: <strong>{analysisSessionId}</strong></p>}
                    {blurResult && (
                      <>
                        <p style={{margin: '0.5rem 0 0', fontSize: '0.9rem', color: '#0C4A6E'}}>
                          Selected ({qualityModeLabels[blurResult.qualityMode] || 'Result'}): <strong>{Number(blurResult.selectedCount || 0)}</strong> / {Number(blurResult.analyzedCount || 0)}
                        </p>
                        {blurResult?.buckets && (
                          <p style={{margin: '0.35rem 0 0', fontSize: '0.8rem', color: '#0C4A6E'}}>
                            Very blurry: <strong>{Number(blurResult.buckets['Very blurry'] || 0)}</strong> · Slightly blurry: <strong>{Number(blurResult.buckets['Slightly blurry'] || 0)}</strong> · Acceptable: <strong>{Number(blurResult.buckets['Acceptable'] || 0)}</strong> · Very sharp: <strong>{Number(blurResult.buckets['Very sharp'] || 0)}</strong>
                          </p>
                        )}
                        <div style={{marginTop: '0.5rem', maxHeight: '200px', overflowY: 'auto', backgroundColor: '#F8FAFC', border: '1px solid #BAE6FD', borderRadius: '0.375rem', padding: '0.5rem'}}>
                          {Array.isArray(blurResult.selectedFiles) && blurResult.selectedFiles.length > 0 ? (
                            blurResult.selectedFiles.map((name) => {
                              const scoreItem = selectedScoreByName.get(name);
                              return (
                                <div key={name} style={{fontSize: '0.8rem', color: '#0F172A', padding: '0.15rem 0'}}>
                                  • {name}
                                  {scoreItem ? ` (blur: ${scoreItem.blurScore}, raw: ${scoreItem.rawSharpness})` : ''}
                                </div>
                              );
                            })
                          ) : (
                            <div style={{fontSize: '0.8rem', color: '#0F172A'}}>No images matched selected quality.</div>
                          )}
                        </div>
                        {blurResult?.calibration && (
                          <p style={{margin: '0.45rem 0 0', fontSize: '0.78rem', color: '#0C4A6E'}}>
                            Auto calibration — mode: <strong>{String(blurResult.calibration.modelUsed || 'classical')}</strong>, status: <strong>{String(blurResult.calibration.modelStatus || 'unknown')}</strong> · mean sharpness: <strong>{Number(blurResult.calibration.meanSharpnessScore || 0).toFixed(2)}</strong>, dynamic threshold: <strong>{Number(blurResult.calibration.dynamicSharpnessThreshold || 0).toFixed(2)}</strong> · Laplacian p10: <strong>{Number(blurResult.calibration.laplacianP10 || 0).toFixed(2)}</strong>, p90: <strong>{Number(blurResult.calibration.laplacianP90 || 0).toFixed(2)}</strong>
                          </p>
                        )}
                      </>
                    )}
                  </>
                )}
              </div>
            )}

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
              <label>
                <input
                  id="detectBlur"
                  type="checkbox"
                  style={{marginLeft:8}}
                  checked={detectBlurEnabled}
                  onChange={(e) => handleDetectBlurChange(e.target.checked)}
                /> Detect blurry
              </label>
              <label><input id="detectLight" defaultChecked type="checkbox" style={{marginLeft:8}}/> Detect bad lighting</label>
              <div className="controls-center">
                <button type="button" onClick={handleAnalyzeZip} disabled={!selectedZipFile || inspectingZip || uploadingZip || processingZip || analyzingBlur} className="btn btn-blue">Run Analysis</button>
              </div>
            </div>

            {showBlurThresholdPopup && (
              <div style={{position:'fixed', inset:0, backgroundColor:'rgba(0,0,0,0.4)', display:'flex', alignItems:'center', justifyContent:'center', zIndex:1000}}>
                <div style={{background:'#fff', borderRadius:'0.5rem', padding:'1rem', width:'min(90vw, 360px)', boxShadow:'0 10px 30px rgba(0,0,0,0.2)'}}>
                  <p style={{margin:'0 0 0.6rem', fontWeight:600, color:'#0F172A'}}>Choose quality range</p>
                  <label style={{display:'block', marginBottom:'0.6rem', color:'#0F172A', fontSize:'0.85rem'}}>
                    Select quality to list:
                    <select
                      value={pendingBlurQualityMode}
                      onChange={(e) => setPendingBlurQualityMode(e.target.value)}
                      style={{display:'block', width:'100%', marginTop:'0.3rem', padding:'0.35rem', border:'1px solid #CBD5E1', borderRadius:'0.35rem'}}
                    >
                      <option value="very_blurry">Very blurry (0–50)</option>
                      <option value="slightly_blurry">Slightly blurry</option>
                      <option value="acceptable">Acceptable (100–300)</option>
                      <option value="very_sharp">Very sharp (300+)</option>
                    </select>
                  </label>
                  <p style={{margin:'0.2rem 0 0.8rem', fontSize:'0.82rem', color:'#334155'}}>
                    Quality is auto-calibrated per ZIP using blur score (0 = sharpest, 100 = blurriest).
                  </p>
                  <div style={{display:'flex', justifyContent:'flex-end', gap:'0.5rem'}}>
                    <button type="button" className="btn btn-black" onClick={handleCancelBlurThreshold}>Cancel</button>
                    <button type="button" className="btn btn-blue" onClick={handleConfirmBlurThreshold}>OK</button>
                  </div>
                </div>
              </div>
            )}

          </form>
        </FormikProvider>
      </div>
    </div>
  );
}
