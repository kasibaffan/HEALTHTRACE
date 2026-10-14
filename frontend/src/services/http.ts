const base=(import.meta.env.VITE_API_URL||'').replace(/\/$/,'');
export class ApiError extends Error { constructor(message:string,public status:number){super(message)} }
export async function requestJson<T>(path:string,init:RequestInit={}):Promise<T>{
 const response=await fetch(`${base}/api${path}`,init);const type=response.headers.get('content-type')||'';const payload=type.includes('application/json')?await response.json().catch(()=>null):null;
 if(!response.ok){const detail=payload&&typeof payload==='object'&&'detail' in payload?String(payload.detail):response.status===404?'The API route was not found. Check the backend URL and deployment proxy.':response.status===502||response.status===503?'The HealthTrace service is unavailable. Please try again shortly.':'The server returned an unexpected response. Please try again.';throw new ApiError(detail,response.status)}
 if(payload===null)throw new ApiError('The server returned an unexpected non-JSON response.',response.status);return payload as T;
}
