const [sharpModule, source, output, trim] = process.argv.slice(2);
const sharp = require(sharpModule);
async function run() {
  let img = sharp(source, {limitInputPixels: 25000000});
  if (trim) img = img.trim({threshold: 12}).extend({top:32,bottom:32,left:32,right:32,background:'#ffffff'});
  await img.resize({width:2000,height:3600,fit:'inside',withoutEnlargement:true}).png().toFile(output);
}
run().catch(() => { process.stderr.write('Image rendering failed\n'); process.exitCode=1; });
