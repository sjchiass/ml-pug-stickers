# File handling
import os

# For stable diffusion image generation
import torch
from diffusers import AutoPipelineForInpainting, AutoPipelineForText2Image
from diffusers.utils import load_image, make_image_grid

# For segmenting the images
import numpy as np
import cv2

# For drawing the text
from PIL import Image, ImageDraw, ImageFont

#
# PUG
#

data = [
    {
        "name": "pirate3",
        "prompt": "a pirate pug wearing a tricorne hat and an eyepath",
        "seed": 58,
        "background_name": "nebula",
        "background_prompt": "colorful nebula, rainbow colours, 8k, space",
        "background_seed": 36,
        "fill": "white",
        "stroke_fill": "black",
    },
    {
        "name": "cyborg",
        "prompt": "a cyborg pug with lasers, cyberpunk, futuristic",
        "seed": 1,
        "background_name": "lightning",
        "background_prompt": "lightning, electricity, pyroclastic cloud lightning",
        "background_seed": 30,
        "fill": "black",
        "stroke_fill": "red",
    },
    {
        "name": "cat",
        "prompt": "a pirate cat wearing a tricorne hat and an eyepatch, cute",
        "seed": 4,
        "background_name": "data",
        "background_prompt": "data, data stream, the cloud, big data, singularity",
        "background_seed": 5,
        "fill": "white",
        "stroke_fill": "black",
    },
]

for pug in data:
    # The pug is generated by Stable Diffusion XL by inpainting
    # This takes an image mask that will tell the model what to replace
    name = pug["name"]
    prompt = pug["prompt"]
    seed = pug["seed"]

    # The background is imply a regular 512x512 image generated by Stable Diffusion
    background_name = pug["background_name"]
    background_prompt = pug["background_prompt"]
    background_seed = pug["background_seed"]

    fill = pug["fill"]
    stroke_fill = pug["stroke_fill"]

    path = f"{name}_infill_sd_xl_s{seed}.png"
    background_path = f"{background_name}_s{background_seed}.png"
    mask_path = f"{name}_infill_sd_xl_s{seed}_mask.png"
    final_path = f"{name}_infill_sd_xl_s{seed}_{background_name}_s{background_seed}.png"

    # Unfortunately the cyborg helmet is hard for grabcut to recognize
    # See further down for the fix
    if name == "cyborg":
        segmentation_fix = True
    else:
        segmentation_fix = False

    #
    # Main pug
    #
    # https://huggingface.co/docs/diffusers/main/en/using-diffusers/inpaint
    if not os.path.exists(path):
        print(f"Now generating {path} ...")

        pipeline = AutoPipelineForInpainting.from_pretrained(
            "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
            torch_dtype=torch.float16,
            variant="fp16",
        ).to("cuda:0")

        pipeline.enable_model_cpu_offload()

        # load base and mask image
        init_image = load_image("./rpug_original.png")
        mask_image = load_image("./rpug_original_mask.png")

        generator = torch.Generator("cuda").manual_seed(seed)
        image = (
            pipeline(
                prompt=prompt,
                image=init_image,
                mask_image=mask_image,
                generator=generator,
            )
            .images[0]
            .save(path)
        )
        del pipeline
        torch.cuda.empty_cache()
        print(f"Saved to {path}")
    else:
        print(f"WARNING {path} already exists")

    #
    # Background
    #
    # Guide: https://huggingface.co/docs/diffusers/main/en/using-diffusers/conditional_image_generation
    if not os.path.exists(background_path):
        print(f"Now generating {background_path} ...")

        pipeline = AutoPipelineForText2Image.from_pretrained(
            "stable-diffusion-v1-5/stable-diffusion-v1-5",
            torch_dtype=torch.float16,
            variant="fp16",
            # device_map='balanced',
        ).to("cuda:0")

        generator = torch.Generator("cuda").manual_seed(background_seed)
        image = (
            pipeline(
                prompt=background_prompt,
                generator=generator,
            )
            .images[0]
            .save(background_path)
        )
        del pipeline
        torch.cuda.empty_cache()
        print(f"Saved to {background_path}")
    else:
        print(f"WARNING {background_path} already exists")

    #
    # Segmentation with grabcut
    #
    # Guide: https://docs.opencv.org/3.4/d8/d83/tutorial_py_grabcut.html
    #
    # The reason this is tricky is for two reasons
    # First, the inpainting messes with the colours a bit. Open up one of
    # the outputs in a paint editor and you'll see all solid colours's
    # RGB in fact fluctuate a little. This means a simple direct color
    # replace won't work.
    # Second, you can't just make the backrgound an unlikely colour like
    # green beforehand because that will affect the image generation. The
    # background influences the inpaint, see the guide. (I have to confirm
    # this myself.)
    # All that said, this can be handled with a bit of extra code.
    img = cv2.imread(path)

    # For the cyborg pug, the weird hat is too close to the background
    # color, so we have to replace the background with something more
    # easily recognizable
    if segmentation_fix:
        rect = img[155:175, 690:710]
        mask = cv2.inRange(
            img,
            (
                int(np.min(rect[:, :, 0])),
                int(np.min(rect[:, :, 1])),
                int(np.min(rect[:, :, 2])),
            ),
            (
                int(np.max(rect[:, :, 0])),
                int(np.max(rect[:, :, 1])),
                int(np.max(rect[:, :, 2])),
            ),
        )
        img[mask != 0] = (0, 255, 0)

    newmask = cv2.resize(cv2.imread("rpug_original_mask.png", 0), (1024, 1024))

    stickermask_img = cv2.resize(
        cv2.imread("rpug_original_sticker_mask.png", 0), (1024, 1024)
    )
    stickermask = np.zeros(img.shape[:2], np.uint8)
    stickermask[stickermask_img == 0] = 0
    stickermask[stickermask_img == 255] = 1

    mask = np.zeros(img.shape[:2], np.uint8)
    mask[newmask == 0] = 0
    mask[newmask == 255] = 3

    bgdModel = np.zeros((1, 65), np.float64)
    fgdModel = np.zeros((1, 65), np.float64)

    cv2.grabCut(img, mask, None, bgdModel, fgdModel, 5, cv2.GC_INIT_WITH_MASK)

    # Where the mask is 3, that's where the model guesses the pug is
    mask2 = np.where(mask == 3, 1, 0).astype("uint8")

    #
    # Contours
    #
    # Now we need to fill in any areas missed inside the pug
    # We use OpenCV to find the pug's contour
    cnts = cv2.findContours(mask2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = cnts[0] if len(cnts) == 2 else cnts[1]

    for c in cnts:
        cv2.drawContours(mask2, [c], 0, 1, -1)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))
    opening = cv2.morphologyEx(mask2, cv2.MORPH_OPEN, kernel, iterations=2)

    # invert
    opening = np.where(opening == 1, 0, 1)

    mask3 = opening * stickermask
    mask3[mask3 == 1] = 255

    cv2.imwrite(mask_path, mask3)

    #
    # Combining everything into final product
    #
    def write_rpug(im, fill="white", stroke_fill="black"):
        font = ImageFont.truetype(
            "LiberationSans-Bold.ttf", (im.width + im.height) // 16
        )
        imdraw = ImageDraw.Draw(im)
        _, _, w, h = imdraw.textbbox(
            (0, 0), "RPUG", font=font, stroke_width=(im.width + im.height) // 256
        )
        imdraw.text(
            ((im.width - w) / 2, (51 * im.height / 64) - (h / 2)),
            text="RPUG",
            fill=fill,
            stroke_fill=stroke_fill,
            stroke_width=(im.width + im.height) // 256,
            font=font,
        )

    base = Image.open(path)
    mask = Image.open(mask_path)
    background = Image.open(background_path).resize((mask.width, mask.height))

    base.paste(background, mask=mask)
    write_rpug(base, fill=fill, stroke_fill=stroke_fill)
    base.save(final_path)
