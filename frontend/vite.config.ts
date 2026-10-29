import { defineConfig } from 'vite';
export default defineConfig({build:{rollupOptions:{input:{main:'index.html',calibration:'calibration.html'}}},server:{allowedHosts:['terminal.local'],proxy:{'/api':'http://127.0.0.1:8000','/ws':{target:'ws://127.0.0.1:8000',ws:true}}}});
