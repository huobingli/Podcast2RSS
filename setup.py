from setuptools import setup, find_packages

setup(
    name="podcast2rss",
    version="0.1.0",
    description="将小宇宙播客转换为RSS，集成通义听悟实现音频转文字功能",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="hsiangyuHuang",
    url="https://github.com/hsiangyuHuang/Podcast2RSS",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "pyyaml>=6.0",
        "python-dotenv>=1.0.0",
        "requests>=2.31.0",
        "pendulum>=2.1.2",
        "retrying>=1.3.4",
    ],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    entry_points={
        "console_scripts": [
            "podcast2rss=src.main:main",
        ],
    },
)
