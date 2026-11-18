// Production bundling uses esbuild directly to avoid Rollup's CommonJS parsing error
// observed with react-dom/client.js in the Fedora Docker build.
import { build } from 'esbuild';
import { mkdir, readFile, rm, writeFile, access, copyFile } from 'node:fs/promises';
import { deflateSync } from 'node:zlib';
import { join } from 'node:path';

const output = 'dist';
const entry = join(output, 'assets');
await rm(output, { recursive: true, force: true });
await mkdir(entry, { recursive: true });

await build({
  entryPoints: ['src/main.jsx'],
  outdir: entry,
  entryNames: 'app',
  bundle: true,
  platform: 'browser',
  format: 'esm',
  target: ['es2020'],
  jsx: 'automatic',
  minify: true,
  legalComments: 'none',
  logLevel: 'info',
});

// Generate dependency-free PNG icons for Safari/iOS and Android installs.
// Branded 'H' mark. No external images or fonts.
function crc32(buffer) {
  let crc=0xFFFFFFFF;
  for(const byte of buffer) {
    crc ^= byte;
    for(let k=0;k<8;k++) crc = (crc&1)?(crc>>>1)^0xEDB88320:(crc>>>1);
  }
  return (crc^0xFFFFFFFF)>>>0;
}
function chunk(type,data=Buffer.alloc(0)) {
  const name=Buffer.from(type);
  const size=Buffer.alloc(4);
  size.writeUInt32BE(data.length);
  const checksum=Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(Buffer.concat([name,data])));
  return Buffer.concat([size,name,data,checksum]);
}
function image(size) {
  const rows=Buffer.alloc((size*4+1)*size);
  for(let y=0;y<size;y++){
    const row=y*(size*4+1);
    for(let x=0;x<size;x++){
      const pos=row+1+x*4, xx=x/size, yy=y/size;
      const dx=Math.abs(xx-.5),dy=Math.abs(yy-.5);
      const round=dx<.37 && dy<.37 ||
        Math.hypot(Math.max(0,dx-.29),Math.max(0,dy-.29))<.08;
      // Distinctive light green H: two pillars and connector.
      const mark=((xx>.29&&xx<.40)||(xx>.60&&xx<.71))&&yy>.28&&yy<.72 ||
                 (xx>.37&&xx<.64&&yy>.45&&yy<.55);
      const c=!round?[10,13,18,255]:mark?[127,229,186,255]:[19,44,49,255];
      rows[pos]=c[0];rows[pos+1]=c[1];rows[pos+2]=c[2];rows[pos+3]=c[3];
    }
  }
  const header=Buffer.alloc(13);
  header.writeUInt32BE(size,0);header.writeUInt32BE(size,4);
  header[8]=8;header[9]=6;
  return Buffer.concat([
    Buffer.from([137,80,78,71,13,10,26,10]),
    chunk('IHDR',header),chunk('IDAT',deflateSync(rows)),
    chunk('IEND')
  ]);
}
await mkdir(join(output,'pwa'),{recursive:true});
for(const px of [192,512]) await writeFile(join(output,'pwa','icon-'+px+'.png'),image(px));
await copyFile('pwa/manifest.webmanifest',join(output,'manifest.webmanifest'));
await copyFile('pwa/sw.js',join(output,'sw.js'));

const html = await readFile('index.html', 'utf8');
const inputTag = '<script type="module" src="/src/main.jsx"></script>';
if (!html.includes(inputTag)) {
  throw new Error('index.html is missing the expected development entry point');
}
await Promise.all([
  access(join(entry, 'app.js')),
  access(join(entry, 'app.css')),
]);
await writeFile(
  join(output, 'index.html'),
  html.replace(inputTag,
    '<link rel="stylesheet" href="/assets/app.css" />\n    <script type="module" src="/assets/app.js"></script>'),
);
console.log('HomeLab OS production assets built successfully.');
